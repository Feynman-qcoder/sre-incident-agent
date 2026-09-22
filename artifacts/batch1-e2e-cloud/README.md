# batch1-e2e-cloud — 批次 1 云端 E2E 证据存档

> **来源**：阿里云 ECS 实例（标识已脱敏）`/root/otel-sre-copilot/artifacts/watchdog/` + `/root/b1_*.log`
> **取回时间**：2026-09-21 21:05（补取 9/21 增量：21:10）
> **内容**：39 份调查报告 JSON + 12 份 gateway 审计 jsonl + 13 份原始日志
> **性质**：真实集群注入 + watchdog 自动调查的原始产物，未做任何修改

## 为什么在这里

批次 1（数据与规则丰富）执行时，E2E 证据落在**云端工作目录**，本地只回传了运行快照（`snapshots/`）。
2026-09-21 盘点发现以下证据此前**未取回本地**，本次一并存档：

| 证据 | 说明 |
|---|---|
| `20260918T081250Z_KubePodNotReady_email.json` | **008 A 类全链路核心证据**（告警 81s → 开查 30s → top-1 email/pod_crash 精确命中） |
| `20260918T1048–1349Z_OtelDemoTelemetryAbsent_quote.json` ×5 | **absent 规则真实触发实录**（9/18 18:48–21:49 连续 5 次调查；18:48 那次即验证时"路径 B"的同名报告，19:33 起为断流跨过 15min 阈值后的真实触发） |
| `20260918T*_OtelDemoHighErrorRate/HighLatencyP99/HighClientErrorRate_*.json` | 011 弧线两遍期间的完整调查集（含背景误报实录：fraud-detection / recommendation / ad / payment） |
| `b1_s011_arc1_wd.log` / `b1_s011_arc2_wd.log` | **011 B→A 弧线两遍完整事件链原始日志**（96KB / 92KB）——批次 1 执行记录量化要求的原始出处 |
| `b1_s008_e2e_wd.log` / `b1_s008_e2e_inject.log` | 008 E2E 原始日志（告警→开查时延的原始出处） |
| `b1_s009/010/010b/010c.log` | 009/010 采集与重采过程日志（010 三次采集的完整记录） |
| `absent_wd.log` | absent 验证期间的 watchdog 日志 |
| `20260921T*.json` ×4 | 9/21 云端 E2E 增量（frontend HighErrorRate 系列；含 11:26 那份此前本地缺失） |
| `tool_audit_*.jsonl` ×12 | SafeToolGateway 全量审计（批次 1 期间的每次工具判定） |
| `state.json` / `ack_log.json` | 去重冷却状态 + ack 确认留痕快照 |

## 与既有存档的关系

| 目录 | 覆盖范围 |
|---|---|
| `artifacts/watchdog-e2e-cloud/` | P0 首验（9/16，3 报告 + 8 日志） |
| `artifacts/watchdog-golden-e2e-cloud/` | P1 七场景（9/17，glm-5.3 口径，16 报告 + 场景日志 + 校准数据） |
| `artifacts/watchdog-golden-e2e-cloud-deepseek/` | P1 终验（9/17，deepseek 刷新，15 报告） |
| `artifacts/oncall-e2e-cloud/` | oncall 值守 E2E（9/18 12:57–13:02，6 报告 + 企微截图） |
| `artifacts/watchdog-cloud-final/` | 9/21 首次取回（3 报告 + 10 审计） |
| **`artifacts/batch1-e2e-cloud/`（本目录）** | **批次 1 全量 + 9/21 增量补全（39 报告 + 12 审计 + 13 日志）** |
| `artifacts/watchdog/` | 本机工作目录（含 gate D 离线回放报告） |

## 附注

- 9/18 18:48 的 `20260918T104842Z_OtelDemoTelemetryAbsent_quote.json` 即 absent 验证时"路径 B"的那份报告——**修正说明**：当时经 `--alerts-file` 离线路径验证了 watchdog 接入（本机），而云端同名报告是**真实触发**产物（断流跨过 staleness 5m + 窗口 10m ≈ 15min 阈值）。
- 各报告 `llm_model` 均为 `deepseek-flash`，`cost_usd` 为 deepseek 实价口径（2026-09-18 后）。
