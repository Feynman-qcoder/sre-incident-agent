# tool-gateway Specification

## Purpose
Safe Tool Gateway："模型负责决定查什么，程序决定能不能查"（SxDevOps 借鉴，原始计划 §十三）。在 Agent 与工具之间插入确定性钳制层 + 全量调用审计——安全从"事实"（工具恰好全只读、模型恰好没越界）升级为"机制"（越界必被拦、每次调用可审计）。

## Requirements

### Requirement: 工具调用钳制

Agent 的每次工具调用 SHALL 经 SafeToolGateway 判定，判定类型为 ALLOW / DENY / CLAMP 三种：

1. **Allowlist**：仅白名单内工具名可执行（默认 = 现有 7 工具），未注册名 DENY（reason=not_in_allowlist）；
2. **Namespace Scope**：`get_pod_events` / `get_service_topology` 的 namespace 参数必须 ∈ 允许集（默认 `{"otel-demo"}`，环境变量可扩），越界 DENY（reason=namespace_out_of_scope）；
3. **Query Window**：`query_prometheus_range` / `search_traces` / `query_loki` 的 start/end 超过调查窗口 + 余量（默认 ±30min）时 CLAMP 到最大允许窗口（reason=window_clamped），并**在返回给 Agent 的结果中显式声明已被钳制**（非静默裁剪——模型知道窗口被改）；
4. **Tool Budget**：单次调查（run）工具调用总数硬上限（默认 20——按"默认值=实测行为上界"原则核定：mem-inject-on 实测单场景最大 17 次 + 余量；`TOOL_BUDGET` 可配）——超出 DENY（reason=budget_exhausted）且返回引导收敛的提示（"Tool budget exhausted. Generate your final report now."）；每工具执行超时（默认 15s，超时返回 `[TOOL TIMEOUT]`，不中断调查）。

DENY 的返回 MUST 是给模型的可理解文本（含 reason），不是异常崩溃。

#### Scenario: namespace 越界被拒

- **WHEN** 模型调用 `get_pod_events(namespace="kube-system")`
- **THEN** 返回 DENY 文本（含 namespace_out_of_scope），审计记录 verdict=DENY；kube-system 数据未被查询

#### Scenario: 超窗查询被钳制且告知

- **WHEN** 模型调用 `query_prometheus_range(start=7天前, end=now)`，调查窗口为近 30 分钟
- **THEN** 实际执行窗口被 CLAMP 到 [调查窗口起点−30min, end]，返回结果的头部含"window clamped"声明；审计记录 verdict=CLAMP 与原/新窗口

#### Scenario: 预算耗尽引导收敛

- **WHEN** 单次调查的第 21 次工具调用发生（TOOL_BUDGET=20）
- **THEN** DENY + 返回预算耗尽与"生成最终报告"引导；调查正常终止于报告生成，无异常

#### Scenario: 正常路径零行为变化

- **WHEN** 模型的调用全部在白名单内、namespace 合规、窗口合规、预算内（当前实测的全部行为）
- **THEN** 全部 ALLOW，工具结果与无 Gateway 时一致；既有单测与评测流程全绿

### Requirement: 工具调用审计

Gateway SHALL 对每次判定（ALLOW/DENY/CLAMP 含超时）追加写审计文件 `artifacts/<run_id>/tool_audit.jsonl`（无 run_id 场景如单测写到 tmp）：每行含 incident_id、tool、args_summary（脱敏摘要 ≤200 字符）、verdict、reason、latency_ms、error、ts。审计与 `tool_calls_log`（grounding 输入）**职责分离**：审计记录"判定过程"（含被拒调用），tool_calls_log 只记"实际执行"（grounding 只校验真实证据）——被 DENY 的调用不得进入 tool_calls_log。

#### Scenario: 被拒调用可审计但不算证据

- **WHEN** 一次调查中发生 2 次 DENY 与 10 次 ALLOW
- **THEN** tool_audit.jsonl 含 12 行（2 DENY + 10 ALLOW）；tool_calls_log 含且仅含 10 条实际执行记录

#### Scenario: 审计喂给演示层

- **WHEN** 查看一次调查的 tool_audit.jsonl
- **THEN** 可直接重构"工具调用时间线"（每次调用的判定/耗时/结果状态）——演示层证据追溯视图的数据源，无需二次解析

### Requirement: 配置与默认值

钳制参数 SHALL 经环境变量配置且默认值即安全值：`TOOL_ALLOWLIST`（默认 7 工具全集）、`TOOL_ALLOWED_NAMESPACES`（默认 otel-demo）、`TOOL_QUERY_WINDOW_MARGIN_MIN`（默认 30）、`TOOL_BUDGET`（默认 20）、`TOOL_TIMEOUT_S`（默认 15）。默认配置 MUST 与当前实测行为上界一致（即"开箱不改变现状，只拦越界"）。

#### Scenario: 默认值零回归

- **WHEN** 不设任何 TOOL_* 环境变量，运行既有全量单测与 7 场景 replay
- **THEN** 全部 ALLOW，评测指标与最新同码基线（mem-inject-on run）口径一致（Acc@1=1.000）；tool_audit 全记录 verdict=ALLOW
