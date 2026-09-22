# alert-watchdog Specification

## Purpose
让 SRE 诊断 Agent 具备「自己发现异常」的能力：持续轮询 Prometheus 告警，对**新增的有效告警**自动发起一次 live 模式事故调查并落盘报告，把"给定窗口的诊断者"升级为"告警驱动的值班 Agent"。

## Requirements

### Requirement: 告警轮询与噪声过滤

系统 SHALL 按可配置间隔（默认 ≤30 秒）轮询 Prometheus `/api/v1/alerts` 端点，并 MUST 只处理满足全部以下条件的告警：属于白名单的告警名、且目标 namespace 为 `otel-demo`。白名单 MUST 可配置，其初始集合为 6 项 —— pod 类 4 项（`KubePodCrashLooping`、`KubePodNotReady`、`KubeDeploymentReplicasMismatch`、`KubeStatefulSetReplicasMismatch`，实测该集群的 OOM 故障以 `KubePodCrashLooping` 形式出现）+ 黄金指标 2 项（`OtelDemoHighLatencyP99`、`OtelDemoHighErrorRate`，由 `golden-signal-alerting` 能力提供）。白名单之外的告警 MUST 被忽略并计入 `alert_filtered` 日志（原因取 `not_in_whitelist` 或 `wrong_namespace`），不得触发任何调查。

#### Scenario: 环境固有噪声不触发调查
- **WHEN** 当前集群存在多条历史遗留告警（实测两个时点分别为 23 条与 25 条，多为 kind 单节点环境固有噪声：controller-manager / scheduler 不可达、API 预算燃烧、TargetDown 等；其中含 2 条 kube-system 的 `KubePodCrashLooping`，应被 namespace 规则拦下）
- **THEN** watchdog 运行 `--once` 或 `--dry-run` 时产生 0 次调查，且每条被忽略的告警都有 `alert_filtered` 结构化日志可查

#### Scenario: 白名单内的新告警通过
- **WHEN** `otel-demo` namespace 出现一条 `KubePodCrashLooping`（firing）告警
- **THEN** 该告警通过过滤进入去重检查，日志记录 `alert_seen`

#### Scenario: 黄金指标告警通过过滤
- **WHEN** Prometheus 出现 `OtelDemoHighLatencyP99{namespace="otel-demo", service_name="product-catalog"}`
- **THEN** 该告警通过白名单与 namespace 检查，日志记录 `alert_seen`

### Requirement: 指纹去重与冷却

系统 SHALL 以 `hash(alertname + namespace + service/pod 标识)` 为指纹维护已处理状态表（JSON 落盘、进程重启不丢失）。去重 MUST 分两层：

1. **指纹级**（与 P0 相同）：同一指纹在冷却期内（默认 45 分钟）MUST 只触发一次调查，重复告警记录 `skipped_cooldown`；
2. **服务级聚合**（本变更新增）：同一 `service` 的**任意**白名单告警在服务冷却期内（默认与指纹冷却相同、`--service-cooldown-min` 可配）MUST NOT 再触发新调查，命中时记录 `skipped_service_cooldown`（含先前的触发告警名）。指纹格式与 P0 的 `state.json` 保持兼容（既有字段不变，新增服务级时间戳字段）。

#### Scenario: 故障持续期间不重复调查
- **WHEN** 同一服务的同一故障告警持续 firing 超过一个轮询周期
- **THEN** 只产生 1 次调查，后续轮询记录 `skipped_cooldown` 而不再开查

#### Scenario: 同一故障的多个告警名各自独立去重
- **WHEN** 同一 pod 故障先后产生 `KubePodNotReady` / `KubeDeploymentReplicasMismatch` / `KubePodCrashLooping` 三个不同白名单告警名（P0 实测行为为 3 次独立调查、成本 $0.0131）
- **THEN** 服务级聚合冷却生效后仅首个到达的告警触发 1 次调查，其余两条被 `skipped_service_cooldown` 拦截（预期成本 ≈$0.004）；指纹级去重语义不变 —— 若服务冷却被配置为 0（关闭聚合），三个指纹仍各自最多调查 1 次（回退为 P0 行为）

#### Scenario: 同轮多条告警同服务去重
- **WHEN** 同一轮轮询中出现同一服务的多条不同白名单告警名（如故障初期 `KubePodNotReady` 与 `KubeDeploymentReplicasMismatch` 同轮到达——2026-09-17 E2E 001 实测形态）
- **THEN** 至多触发 1 次调查：实现 MUST 在 `process()` 内维护同轮（cycle-local）服务记账——一条告警通过全部检查后即占用该服务本轮额度，同轮后续同服务告警记 `skipped_service_cooldown`（`reason="same_cycle"`、含首条告警名）。`--service-cooldown-min 0`（关闭聚合）时该同轮记账 MUST 一并关闭（回退纯指纹行为）。缺陷 D-P1-01（同轮多条 passed 绕过，001 实测 2 次调查）已于 P1.5 修复（提交 `88ac41c`，单测 + 离线 dry-run 断言 1 passed + 1 skipped 实测通过，43+94 单测全绿）

#### Scenario: 服务冷却不跨服务误伤
- **WHEN** cart 处于服务冷却期内，此时 shipping 触发白名单告警（不同服务）
- **THEN** shipping 的告警正常通过两层去重并触发调查

### Requirement: 自动发起 live 调查

对通过过滤与去重的新增告警，系统 MUST 自动组装调查窗口 `[alert.activeAt − 120s, now]`（实测核对：`activeAt=13:42:32Z` → `window_start=13:40:32Z`）并复用既有 live 数据源与诊断图执行一次完整调查，产出与现有 `InvestigationReport` 同构的报告（含 root causes、hypotheses、evidence）。**从告警 `activeAt` 到调查开始的延迟 SHOULD ≤120 秒**（实测 2 秒）—— 该判据衡量 watchdog 自身的响应能力，目的是保证证据不过期（K8s 事件 TTL 约 1 小时、事件查询窗口 10 分钟，且调查窗口已回溯至 `activeAt − 120s`）。

上游告警链路（kube-state-metrics scrape ≈30 秒 + Prometheus 规则评估 ≈60 秒，实测「注入 → 出现告警」≈90 秒）**不属 watchdog 控制范围**，故本规范不对「故障注入 → 调查开始」的端到端时延提出要求（实测该值为 94 秒，其中 watchdog 自身仅占 2 秒）。

#### Scenario: pod 崩溃故障被自动定位
- **WHEN** 向 `otel-demo` 注入 checkout 服务 pod_crash 故障（场景 001 同款），该故障在 Prometheus 中产生 pending/firing 的白名单告警
- **THEN** watchdog 在**告警出现后的 ≤30 秒内**自动开始调查（实测 2 秒），且最终报告 top-1 根因为 checkout / pod_crash（实测 confidence 0.92；`incident_id` 以 `watchdog-` 开头，可反查触发告警）

### Requirement: 成本与并发护栏

系统 MUST 保证同一时刻至多一个调查在执行（新告警触发时若忙则排队或按策略丢弃并记录）；每小时自动调查次数 MUST 不超过可配置上限（默认 6）；单次调查失败重试 MUST ≤2 次。

#### Scenario: 并发告警不并发烧钱
- **WHEN** 冷却期内两个不同服务同时触发白名单告警
- **THEN** 调查串行执行（先到先查），且每小时总数不超过上限

### Requirement: 后端健康检查与降级

触发调查前系统 SHALL 对 Prometheus / Tempo / Loki 后端做就绪检查；任一失败时 MUST 延后重试（最多 3 次）而不产生无效报告。调查过程中单个工具查询失败 MUST NOT 中断整体调查（沿用现有工具层降级机制）。

#### Scenario: 后端未就绪时不产生垃圾报告
- **WHEN** Prometheus `/-/healthy` 或 Tempo `/ready` 返回非 200
- **THEN** 本次触发延后重试，不启动调查，不落盘任何报告

### Requirement: 输出与可观测性

每次自动调查 MUST 将报告落盘至 `artifacts/watchdog/<timestamp>_<alertname>_<service>.json`，并输出结构化日志（`alert_seen` / `alert_filtered` / `investigation_started` / `investigation_complete` / `skipped_cooldown`）。`--dry-run` 模式 MUST 只打印"会做什么"而不执行调查、不调用 LLM。

#### Scenario: dry-run 零成本演练
- **WHEN** 以 `--dry-run --once` 运行
- **THEN** 输出"若非 dry-run 将调查哪些告警、其余告警为何被过滤"的完整说明，产生 0 次 LLM 调用与 0 个报告文件

### Requirement: 只诊断不修复

watchdog 及其触发的调查 MUST NOT 对集群做任何变更操作（重启 pod、改副本数、扩缩容等均禁止）；报告中的修复建议仅为文本输出。

#### Scenario: 诊断全程零变更
- **WHEN** watchdog 完成一次自动调查
- **THEN** 集群资源（deployments/pods/configmaps 等）状态与调查前完全一致

### Requirement: 与现有链路互不影响

watchdog MUST 作为纯新增入口存在：不修改现有 replay 评测链路、诊断图、数据源协议的行为；watchdog 故障 MUST NOT 影响既有 CLI 与评测命令的正常运行。

#### Scenario: 存档点行为不变
- **WHEN** 在未启用 watchdog 的情况下运行原有 replay 评测
- **THEN** 结果与存档点 `f75a4a4` 上的行为完全一致

### Requirement: 黄金指标告警的服务解析与故障提示

对黄金指标类告警（`OtelDemoHighLatencyP99` / `OtelDemoHighErrorRate`），服务名 MUST 直接取自 labels 的 `service_name`（其值即 Astronomy Shop 服务名），优先级高于 pod 名解析；故障类型 hint 分别为 `high_latency` / `http_abort`（仅 hint，调查中 Agent 自行修正，与 pod 类告警一致）。watchdog 的自动调查覆盖 SHALL 因此扩展至全部 7 类评测故障（pod_crash / high_latency / http_abort / cpu_stress / memory_stress——后两者经延迟/错误率表征触发）。

#### Scenario: 延迟类故障被自动定位
- **WHEN** 向 product-catalog 注入 high_latency 故障（场景 002 同款），触发 `OtelDemoHighLatencyP99{service_name="product-catalog"}`
- **THEN** watchdog 自动开始调查（`incident_id` 以 `watchdog-OtelDemoHighLatencyP99-` 开头），最终报告 top-1 根因为 product-catalog / high_latency

#### Scenario: 错误率类故障被自动定位
- **WHEN** 向 payment 注入 http_abort 故障（场景 003 同款，网络层掐断响应）
- **THEN** 如实记录的可观测性边界适用：`OtelDemoHighErrorRate` 对网络层 abort **不产生触发**（受击服务的 SERVER span 正常结束、无 ERROR 标记——错误率规则对该类故障天然失明，2026-09-17 E2E 003 实测 0 份 HighErrorRate 报告）；故障经 `OtelDemoHighLatencyP99` 在**调用方**（frontend/checkout）以延迟表征触发，watchdog 照常自动开查，但报告 top-1 可能落在级联症状服务而非 payment。覆盖该盲区需后续扩展 CLIENT span 错误率规则（P2 方向，本变更不含）
