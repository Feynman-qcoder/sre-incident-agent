# golden-signal-alerting Specification

## Purpose
基于业务 spanmetrics（`calls_total` / `duration_milliseconds_bucket`，与 `src/telemetry_queries.py` 同源）的自定义 Prometheus 告警规则：p99 延迟**相对跳变**与错误率**绝对阈值**两条，补上 kube-prometheus-stack 默认规则（只看 pod/节点/控制面）完全触及不到的故障类别 —— 延迟、错误率、资源压力的遥测表征。

## Requirements

### Requirement: p99 延迟相对跳变告警

系统 SHALL 提供名为 `OtelDemoHighLatencyP99` 的告警规则：当某服务的当前 5 分钟窗口 p99 延迟相对其参考窗口（30 分钟前的 5 分钟窗口）p99 的比值超过部署前经实测校准的阈值时触发。查询 MUST 基于 spanmetrics 的 `duration_milliseconds_bucket`、限定 `span_kind="SPAN_KIND_SERVER"`、按 `service_name` 聚合（与诊断 Agent 的黄金指标查询同源，见 `src/telemetry_queries.py`）。规则 MUST NOT 使用绝对毫秒阈值（该集群健康基线 p99 本身为多秒级噪声，实测 200ms 量级的注入延迟会被基线淹没）。比值判定 MUST 包含近零基线保护：仅当参考窗口 p99 超过**环境校准下限**（校准期按健康基线实测核定并记录于校准文档；当前 8vCPU/PL1 环境实测 = **1ms**，部署于 `infra/prometheus-rules/golden-signals.yaml`）时该服务的比值才参与判定，低于下限的服务该周期 MUST NOT 触发（2026-09-17 旧机校准 round 2 实证：近零分母导致比值爆炸至 recommendation 686x / product-catalog 90x）。**下限常量是环境相关的，禁止跨环境照抄**：旧机多秒级基线时为 100ms，新环境毫秒级基线（全部 13 服务 1.98–37ms）照抄 100ms 会使规则永不触发——换环境重建后 MUST 重新核定。

#### Scenario: 延迟注入触发告警
- **WHEN** 向 product-catalog 注入 1500ms±300ms 网络延迟（场景 002 同款）
- **THEN** 该服务的 `OtelDemoHighLatencyP99` 进入 pending/firing，且告警 labels 携带 `service_name="product-catalog"`

#### Scenario: 健康稳态不触发
- **WHEN** 集群无故障运行、各服务 p99 处于其自身噪声基线内
- **THEN** 该规则对全部服务保持 inactive（健康期连续观察 ≥30 分钟零误报为校准通过标准）

#### Scenario: 近零基线服务不触发
- **WHEN** 某服务参考窗口 p99 ≤ 环境校准下限（当前环境 1ms；即无流量/近零 series），当前窗口出现相对跳变
- **THEN** 该服务的 `OtelDemoHighLatencyP99` 保持 inactive——比值被保护条款排除，不因分母近零而误报

### Requirement: 错误率绝对阈值告警

系统 SHALL 提供名为 `OtelDemoHighErrorRate` 的告警规则：当某服务的 SERVER span 错误请求占比（5 分钟窗口内 `status_code="STATUS_CODE_ERROR"` 的 `calls_total` 速率 ÷ 总 `calls_total` 速率）超过 10% 时触发。查询 MUST 按 `service_name` 聚合并限定 `span_kind="SPAN_KIND_SERVER"`。阈值取绝对值（10% 的错误率即 SLO 语义上的明确违约，与健康基线高低无关）。

#### Scenario: 注入 http_abort 触发告警
- **WHEN** 向 payment 注入 HTTP abort 故障（场景 003 同款），其错误占比从 ≈0% 跃升
- **THEN** 该服务的 `OtelDemoHighErrorRate` 触发，labels 携带 `service_name="payment"`

#### Scenario: frontend 健康错误基线不误报
- **WHEN** 集群健康稳态运行（旧环境 browser VU 形态下 frontend 健康错误基线实测 ≈4.4%；2026-09-17 禁 browser 新环境复测 = **0%**，无任何 ERROR span 序列）
- **THEN** 该服务的 `OtelDemoHighErrorRate` 保持 inactive（两形态基线均 < 10% 阈值）；负载形态调整（如禁用 browser VU）MUST 复测其健康错误基线后再认定阈值裕度——**2026-09-17 复测义务已履行并记录于校准文档 §五**（新环境基线 0%，裕度充裕，"重点观察"义务解除）；后续若负载形态再次调整，复测义务重新生效

### Requirement: 告警标签契约

两条黄金指标告警的 labels MUST 包含：`service_name`（触发服务名，供 watchdog 直接解析）与 `namespace: otel-demo`（由规则**静态注入** —— spanmetrics 指标本身不带 namespace 标签，注入是为了满足 watchdog 既有 namespace 过滤规则，使其无需改动）。

#### Scenario: watchdog 既有过滤直接放行
- **WHEN** 黄金指标告警进入 Prometheus `/api/v1/alerts`
- **THEN** 其 labels 中 `namespace="otel-demo"` 与 `service_name=<服务名>` 同时存在，watchdog 的白名单与 namespace 检查不改代码即可通过

### Requirement: 规则可部署与可撤销

规则 SHALL 以单个 YAML（`infra/prometheus-rules/golden-signals.yaml`）交付并经 `kubectl apply` 部署到 monitoring namespace；部署前 MUST 核实 kube-prometheus-stack 的 `ruleSelector` 标签约定（通常需 `release: prometheus`）并使规则文件携带匹配标签。撤销 MUST 只需 `kubectl delete -f` 同一文件，不遗留任何集群状态。规则文件属于仓库交付物（版本化），且 MUST NOT 依赖项目 Python 代码。

#### Scenario: 部署后规则被 Prometheus 加载
- **WHEN** `kubectl apply -f infra/prometheus-rules/golden-signals.yaml` 后查询 `/api/v1/rules`
- **THEN** `OtelDemoHighLatencyP99` 与 `OtelDemoHighErrorRate` 出现在规则列表中且状态为加载（非失败）

#### Scenario: 撤销后恢复 P0 状态
- **WHEN** `kubectl delete -f infra/prometheus-rules/golden-signals.yaml`
- **THEN** Prometheus 规则列表不再包含这两个告警名，watchdog 行为回到 P0 状态
