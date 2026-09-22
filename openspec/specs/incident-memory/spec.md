# incident-memory Specification

## Purpose
文件记忆库：AI 自动记录 + 人工可编辑的历史经验，调查时确定性注入。**安全原则（用户原始计划 §十二 原文精神）：历史 Incident = 调查 Hint ≠ 当前 RCA Evidence——最终根因必须由当前 Prometheus/Loki/Tempo/K8s 证据支撑，防"过去是 X 就直接猜 X"的污染。**

## Requirements

### Requirement: 文件记忆库结构

系统 SHALL 在仓库内维护 `memory/` 目录作为长期记忆的唯一权威源（git 版本化）：`INDEX.md` 为路由索引（每行一条：service / fault_type → incident 文件指针，纯指针不存内容）；`incidents/<incident_id>.md` 每份含 YAML frontmatter（incident_id / service / fault_type / root_cause_service / root_cause_fault_type / confidence / created_at / source_report）+ 正文（根因摘要 / 修复建议 / 证据要点 ≤5 条）；`notes/lessons.md` 为人工经验层（无强制 schema，供人覆盖/修正 AI 记录）。**索引与文件不一致时，以文件为准，索引是可重建的派生物**（同构于 markdown-agent-memory 的 Source of Truth 原则）。

#### Scenario: 索引可从文件重建

- **WHEN** 删除 INDEX.md 后运行索引重建（导入脚本附带 `--rebuild-index`）
- **THEN** 从 incidents/ 全部 frontmatter 重建的 INDEX 与各文件内容一致（含 service/fault_type/指针），记忆零丢失

#### Scenario: 人工经验层参与检索

- **WHEN** notes/lessons.md 中存在与目标 service/fault_type 匹配的条目（按行内约定标记）
- **THEN** 该条目优先于 AI 历史记录注入（人工判断覆盖 AI 记忆），并在注入块中标注来源为 notes

### Requirement: 调查记忆注入（V1 确定性注入式）

调查启动时 harness SHALL 按 `service_hint + fault_type_hint`（来自告警映射或场景元数据）对 INDEX 做精确匹配，取最近 top-3 历史记录（无匹配则注入空——明确记录 `memory_miss`），构造**独立的 Hint 块**注入 Agent 上下文。Hint 块 MUST 显式包含免责声明（"以下为历史调查参考，非当前证据；最终根因结论必须由当前工具调用证据支撑"）。注入 MUST 可通过环境变量/配置关闭（`INCIDENT_MEMORY=off` 时行为与本变更前完全一致——回归对照的基线路径）。调查完成后 writer SHALL 将本次报告追加为 `incidents/<incident_id>.md` 并更新 INDEX（writer 失败仅告警，不影响调查主流程）。

#### Scenario: 同服务同类型故障的历史被注入

- **WHEN** checkout 服务发生 pod_crash 告警，且记忆库存在 checkout/pod_crash 历史记录（含 root_cause 与修复建议）
- **THEN** Agent 上下文含 top-3 历史摘要 Hint 块；grounding 校验的结果不含记忆内容（记忆不作为证据计分）

#### Scenario: 记忆关闭时行为不变

- **WHEN** 环境变量 INCIDENT_MEMORY=off，运行任意调查
- **THEN** 上下文不含 Hint 块、writer 不写文件，全部行为与变更前一致（逐字节等价的 tool_calls 流不作要求，但评测指标口径不变）

#### Scenario: 无匹配历史

- **WHEN** 目标 service+fault_type 在 INDEX 无任何匹配
- **THEN** 注入块为空或省略，结构化日志记录 `memory_miss`（service/fault_type），调查正常进行

### Requirement: 记忆无害回归门

本变更 MUST 附带记忆有效性评测：开启注入后对 7 场景 replay 重跑（同模型同 seed 同快照，与 `20260917T152725Z` 同口径），**Acc@1 保持 1.000 且 grounding 不低于无记忆基线 −0.05**。若任一场景指标退化：如实记录退化场景与注入的历史内容，定位是"记忆污染"（Agent 依赖历史跳过取证）还是"巧合波动"（LLM 非确定性），**禁止为过门而关闭或篡改记忆内容**；污染案例本身具有记录价值（写进执行记录）。

#### Scenario: 注入后指标不退

- **WHEN** 开启 INCIDENT_MEMORY 并对 7 场景 replay 重跑
- **THEN** Acc@1 = 1.000；各场景 grounding 与基线差 ≥ −0.05；tool_calls 次数无系统性下降（若下降需检查是否跳过取证——记忆提前"喂答案"的污染信号）
