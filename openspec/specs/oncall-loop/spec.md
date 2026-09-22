# oncall-loop Specification

## Purpose
值班协作闭环：集群告警经告警治理（分组/抑制/静默）送达 IM，watchdog 诊断结论与修复建议送达 IM，值守人员确认（ack）留痕。**边界：止步于人工确认，不含任何执行修复动作**（架构性只读原则的最后延伸——"建议人做"与"替人做"之间划线）。

## Requirements

### Requirement: 告警治理与送达（Alertmanager）

系统 SHALL 启用集群内 Alertmanager（kube-prometheus-stack 原生组件，经 `infra/helm/prometheus-values.yaml` 固化启用）作为集群原生告警的治理层：对 `otel-demo` namespace 的告警 MUST 配置路由（按 `alertname` + `service_name/service` 分组、合理 group_interval/wait），并经 webhook receiver 推送企业微信群机器人。抑制（同服务高严重度抑制低严重度）与静默（维护窗口）能力 MUST 至少各有一条可演示配置。原生告警推送与 watchdog 自动调查是**两条并行链路**（Alertmanager 不知道 watchdog 的存在），互不依赖。

#### Scenario: 原生告警经治理到达企微群

- **WHEN** 集群出现 otel-demo namespace 的告警（如注入 pod 故障后 KubePodNotReady firing）
- **THEN** Alertmanager 按分组策略聚合后推送企微群，消息含告警名、服务、状态与实例链接（Alertmanager UI 经 NodePort 可达）

#### Scenario: 维护窗口静默演示

- **WHEN** 对某服务设置静默窗口（amtool 或 UI），窗口内该服务告警继续触发
- **THEN** 企微群不收到该告警推送，静默到期后恢复推送

### Requirement: 诊断结论与修复建议送达（watchdog notifier）

watchdog SHALL 在每次 `investigation_complete` 后将诊断摘要推送企业微信群机器人（webhook URL 经环境变量 `WECOM_WEBHOOK_URL` 注入，不入 git、日志脱敏）。消息 MUST 为 markdown 格式且包含：incident_id、告警名与服务、**top-1 根因（服务/故障类型/置信度）**、根因一句话摘要、**修复建议前 3 条**（`remediation_steps`，已存在于报告 schema）、报告落盘路径、ack 指引（`watchdog-ack` 命令样例）。通知 MUST NOT 阻塞调查主流程：发送失败仅记录结构化事件 `notification_failed`（含错误摘要），调查与落盘行为不变。

#### Scenario: 调查完成触发通知

- **WHEN** watchdog 完成一次调查（investigation_complete）
- **THEN** 企微群收到含 top-1 根因与修复建议前 3 条的 markdown 消息；消息中的报告路径可在磁盘定位到对应 JSON

#### Scenario: 通知失败降级

- **WHEN** webhook 不可达（如 URL 失效/网络断）
- **THEN** watchdog 记录 `notification_failed` 事件并继续运行，本轮调查的报告落盘与状态机不受任何影响

### Requirement: 人工确认留痕（ack）

系统 SHALL 提供 `watchdog-ack` CLI：值守人员对指定 incident_id 确认后，MUST 将确认记录追加至 `artifacts/watchdog/ack_log.json`（含 incident_id、acknowledged_at、acknowledged_by、note 可选），并将对应报告 JSON 回写 `acknowledged_at/by` 字段。ack 是纯记录动作——MUST NOT 触发任何集群操作或自动修复。ack_log 为值守审计的权威数据源（演示层"值班记录"视图的直接数据）。

#### Scenario: 确认诊断并留痕

- **WHEN** 值守人员执行 `python -m scripts.watchdog_ack --incident-id <id> --by <name>`
- **THEN** ack_log.json 追加一条确认记录；对应报告 JSON 出现 acknowledged_at/by；重复 ack 同一 incident MUST 被幂等处理（记录 latest 覆盖或追加，行为在实现中二选一并写入 README）

#### Scenario: 查询值守状态

- **WHEN** 执行 `python -m scripts.watchdog_ack --list`
- **THEN** 输出近期调查及其确认状态（已确认含确认人与时间 / 未确认清单）

### Requirement: 通知配置与凭据管理

群机器人 webhook URL MUST 经环境变量 `WECOM_WEBHOOK_URL` 配置（本地与云端 `.env`，**绝不入 git**——URL 即推送凭据，泄露等同交出群消息通道）。代码与测试 MUST NOT 依赖真实 webhook：单测打本地 HTTP stub 断言请求 payload 结构；E2E 验证才用真实群。未配置 `WECOM_WEBHOOK_URL` 时 watchdog MUST 以显式告警日志跳过通知（`notification_disabled`），不报错退出。

#### Scenario: 未配置 webhook 的默认行为

- **WHEN** 环境变量 WECOM_WEBHOOK_URL 未设置，启动 watchdog
- **THEN** 每次调查完成后记录 `notification_disabled` 事件（一次性或每轮均可，实现二选一），调查流程完全正常——通知是可选增强而非硬依赖

#### Scenario: 凭据不入库

- **WHEN** 本变更实施完成，检查 git 追踪文件与日志产物
- **THEN** 任何被 git 追踪的文件不含 webhook URL 明文；watchdog 日志中的 webhook 相关字段只有 host 或脱敏值
