# CLAUDE.md — 项目约定与工作规范

> 本文件是 AI 编程助手（Claude Code 等）读取的项目上下文，同时作为项目的工程规范说明书。
> 内容与 `README.md`（对外概览）、`deploys/`（部署）、`openspec/specs/`（能力规范）互为印证。

## 项目目标

Kubernetes 微服务（OpenTelemetry Astronomy Shop，15 服务）的事故诊断 Agent：由告警自动触发调查，跨 Metrics / Traces / Logs / K8s 事件多源取证，输出带证据链的 top-k 根因与修复建议，经企微送达并留有 ack 闭环。

**最高优先级：严谨且可复现的评测。** 一个被诚实评测的 MVP 优于一个未被评测的复杂系统。**代码写了 ≠ 评测验证过**——任何能力声明都必须有实测数据支撑。

## 核心原则

1. **评测优先**：任何 Agent 逻辑改动前，先确认评测链路本身可信（同 run 对照、ground truth 正确、grounding 校验有效）。
2. **改动前先测基线**：没有 before 就没有 improvement——量化记录进 `fupan/` 下的量化台账（**本地过程文档，不入库；见 `.gitignore`**；含口径 / 测法 / 证据路径）。
3. **可复现**：seeds 显式（`CHAOS_SEED` / `RANDOM_SEED`）、快照与评测产物全量入库、`clone` 后 `make demo-all` 必须能端到端跑通。
4. **诚实是卖点**：幻觉告警不隐藏、未验证项明确标注、"信号不可得"的场景作为诚实零分保留；禁止在任何文档中夸大数字。
5. **不过度工程**：抽象只在简化评测或复现时引入；每一层新增机制都要能回答"解决哪个具体问题"。
6. **约定式变更**：任何能力变更走 OpenSpec 流程（proposal / spec / design / tasks 四件套），完成后归档入 `openspec/specs/`。

## 技术栈（当前实际）

| 层 | 选型 | 说明 |
|---|---|---|
| 集群 | kind | 可复现、CI 友好、NodePort 简单 |
| SUT | OTel Astronomy Shop（helm） | OTel 原生、~15 微服务 |
| 遥测 | Prometheus（kps）+ Tempo + Loki | 经 OTel Collector（DaemonSet）单入口分发 |
| 故障注入 | Chaos Mesh | CRD YAML → 机器可读 ground truth |
| Agent | LangGraph + langchain_openai | StateGraph 显式状态、工具循环、条件边 |
| LLM | `deepseek-flash`（OpenAI 兼容） | 实测选型：同任务较 glm-5.3 提速 6.1×、质量不退；env 变量名沿用 `NIM_*` 前缀 |
| 评测 | 自研（`eval/`） | 同 run 四方法对照 + grounding 外部校验 + 3 轮重跑 |
| Python | 3.11+（开发机 3.13）| ruff + pytest；Pydantic v2 全量 schema |

## 环境与配置

```bash
# .env（不入库）——变量名沿用 NIM_* 前缀，可指向任意 OpenAI 兼容端点
NIM_API_KEY=<key>
NIM_BASE_URL=https://api.deepseek.com
NIM_MODEL=deepseek-flash
PROMETHEUS_URL=http://localhost:9090
TEMPO_URL=http://localhost:3200
LOKI_URL=http://localhost:3100
KUBECONFIG=<绝对路径>          # 波浪号不展开，必须绝对路径
CONTEXT_BUDGET_TOKENS=28000
MAX_TOOL_ITERATIONS=8
```

## 常用命令

```bash
# 部署与生命周期
make setup / up / down / health-check

# 故障注入 + 快照采集（写入 snapshots/<id>/ground_truth.json）
make fault SCENARIO=scenarios/mvp/001-checkoutservice-pod-crash.yaml

# Agent
make investigate INCIDENT_ID=... START=... END=...   # 手工指定窗口
make watchdog                                         # 告警驱动值守（长跑）

# 评测（同 run 四方法 + 对照报告）
make eval-all / compare
make eval-replay RUN_ID=<id>                          # 确定性复验

# 演示层
make demo-offline        # 离线重建前端数据（零 LLM，可断网）
make demo-all            # 评测 + 重建（一键复现，~4 分钟/$0.02）
make demo-refresh        # 评测 + 自动追加白名单 + 重建（新 run 进界面）

# 开发
make test        # pytest（当前 139 用例）
make lint        # ruff
```

## 代码约定

- **无 `print()`** → `structlog`（结构化日志，事件名 + 关键字段）。
- **无 secrets 入代码** → `.env`（`.env.example` 入库，`.env` 忽略）；凭据类字段日志只打 host 与长度。
- **Pydantic v2** 承载所有对外 schema（`InvestigationReport` 等）；报告与评测产物同构。
- **模块化与低耦合**：单一职责分文件（如 watchdog：`alerter` 过滤去重 / `mapping` 告警映射 / `runner` 编排）；耦合点只允许通过既有接口（`DataSource` 协议、`build_graph(ds)`、`initial_state()`）。
- **注释只写 WHY**，不写 WHAT。
- 测试：pytest；新增机制必须带守护测试（含反向断言，如"被 DENY 的调用不进入证据计分"）。

## 评测协议（不可简化）

1. 场景定义于 `scenarios/mvp/*.yaml`（service / fault_type / Chaos CRD / 期望）。
2. `make fault` → 注入 → 采集 → 写 `ground_truth.json`（**采集后必须校验故障真实注入**——曾因 selector 标签错误导致 0% 注入而不知）。
3. 评测四方法**同 run、同快照、同 seed**：Agent / Z-score / Composite Z / Random——跨 run 拼接在方法学上不成立。
4. 指标口径（`eval/metrics.py` 外部计分，**禁止 Agent 自报**）：Acc@1/Acc@3/MRR/fault_type_accuracy/grounding_score/latency_s/cost_usd。
5. **grounding 校验**：每条 EvidenceItem 必须能回溯到 `tool_calls_log` 的原始记录；`grounding_score < 0.8` 标记 `[HALLUCINATION WARNING]` 并**在界面固定展示不可折叠**。
6. 稳定性：关键结论需 3 轮独立重跑（seed 42/43/44）；基线类确定性算法三轮必须逐场景全等。
7. 成本口径：deepseek 官方实价（cache-miss 保守计费），价目表在 `src/utils/cost.py` 带来源注释。

## 安全护栏（SafeToolGateway）

- **四类确定性钳制**：工具白名单 / namespace 作用域（默认 `otel-demo`）/ 查询窗口钳制（超窗 **告知式** CLAMP，禁止静默裁剪）/ 调用预算 + 超时。
- **全量审计**：每次判定（ALLOW / DENY / CLAMP / timeout）落 `tool_audit.jsonl`；**被 DENY 的调用绝不进入 `tool_calls_log`**（证据链与判定职责分离）。
- **只读工具集**：无 write 权限工具——刻意止步于 ack 确认，不做自动修复（blast radius 不可控）。
- **记忆隔离**：`memory/` 的注入内容只进独立提示消息（Hint），**绝不参与证据校验**（防"历史答案冒充当前证据"）。
- **测试隔离**：涉及 `memory/` 等副作用写入的测试必须通过 `tests/conftest.py` 的 autouse fixture 隔离到 tmp（曾发生 stub 报告覆盖真实记忆的事故——见 `memory/notes/lessons.md`）。

## 能力边界（已知，勿"顺手修复"）

| 边界 | 现象 | 状态 |
|---|---|---|
| 高基线服务 | p99 恒顶格，相对跳变规则失明（009 实测） | SLO 燃烧率语义 = 已评估方向 |
| 低流量服务 | 直方图无样本（010 实测） | absent 告警已补盲（触发时延 ≈ staleness 5m + 窗口 10m） |
| 秒级容器事件 | 重启间隙 < 30s 采集粒度（007） | 事件直推 = 已评估方向 |
| 网络层故障 | 不落 SERVER span（003/011） | CLIENT span 规则已实现，基线复验待环境恢复 |
| 中断恢复 | 三层语义各有测试守护（`tests/test_recovery.py`） | 断点续跑刻意不做（单次调查 30s） |

以上均为**有实测背书的结论**，不是待修 bug——改动前先读 `fupan/复盘-架构答疑II-运行时恢复与扩展边界.md`（本地文档，不入库）。

## AI 助手工作纪律

- **失败两次停手**：同一操作连续失败 ≥2 次 → 停止重试，做根因诊断（完整报错 / 最小复现 / 查依赖链），15 分钟无解则带证据上报。
- **量化记录**：完成改动后按台账格式回报（改动 → 指标 before/after → 测法 → 证据路径）。
- **汇报原始输出**：验证门的结论必须附命令原始输出，不接受"我跑过了全绿"式转述。
- **文档随事实演进**：勘误或行为变更时，同步 grep 全部叙事文档（README / deploys / 剧本 / 本文件），避免口径不一致。

## 归档与证据索引

> `fupan/` 为**本地过程文档目录（不入库、不上传仓库**，见 `.gitignore`）：执行记录 / 验收报告 / 复盘 / 量化台账 / 演示剧本 / 部署速查手册。下述条目仅对本机开发者可见；仓库内可公开的证据以 `openspec/specs/`、`artifacts/`、`snapshots/`、`deploys/` 为准。

| 位置 | 内容 | 可见性 |
|---|---|---|
| `openspec/specs/` | 七大能力规范（alert-watchdog / golden-signal-alerting / evaluation-methodology / oncall-loop / incident-memory / tool-gateway / local-demo-pack） | 公开 |
| `artifacts/` · `snapshots/` | 评测与调查产物、遥测快照（复现数据源） | 公开 |
| `deploys/` | 本地 / 阿里云 ECS 两种部署方式 + 部署工具脚本 | 公开 |
| `fupan/` 量化台账 | 全量量化素材（before/after + 测法 + 证据路径） | 本地 |
| `fupan/演示剧本.md` | 5 / 15 分钟演示脚本 + 追问应对 | 本地 |
| `memory/notes/lessons.md` | 人工运维经验层（优先级高于 AI 自动记录） | 公开 |
