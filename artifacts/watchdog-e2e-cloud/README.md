# 云端 E2E 证据归档（watchdog P0，2026-09-16）

> 来源：阿里云 ECS 实例（释放前取回，2026-09-16 22:42；实例标识已脱敏）
> 对应验收：P0 watchdog 云端验收（8/8 PASS）—— 本目录是验收报告中引用的云端原件。

## reports/（watchdog 自动调查的 3 份报告 + 冷却状态）

同一故障（checkout pod_crash，场景 001 注入）触发 3 个白名单告警名，各自动调查一次：

| 文件 | incident_id | top-1 | conf | cost_usd |
|---|---|---|---|---|
| `20260916T134557Z_KubePodNotReady_572wp.json` | watchdog-KubePodNotReady-195e11da | checkout/pod_crash | 0.92 | $0.00355 |
| `20260916T134833Z_KubeDeploymentReplicasMismatch_state.json` | watchdog-KubeDeploymentReplicasMismatch-88f37cbc | checkout/pod_crash | 0.92 | $0.00400 |
| `20260916T135016Z_KubePodCrashLooping_572wp.json` | watchdog-KubePodCrashLooping-316567f7 | checkout/pod_crash | 0.92 | $0.00556 |

`state.json`：指纹冷却状态表（3 指纹 + 3 条调查记录）。

## logs/

| 文件 | 内容 |
|---|---|
| `watchdog_e2e.log` | **E2E 全程日志**（五类结构化事件；含 `investigation_started`×3、`skipped_cooldown`×9） |
| `wd_dryrun_cloud.log` | 门 B1：23 条真实噪声 → 0 调查 |
| `wd_trace.log` | 告警链路跟踪（activeAt → 开查 2 秒的原始记录） |
| `wd_inject.log` / `wd_inject2.log` | 第一次注入（零告警，ksm 重启断流）与第二次注入（成功） |
| `wd_k8s_before.txt` / `wd_k8s_after.txt` | 门 B4 零变更：调查前后 K8s 资源快照（26 pod + deployments 完全一致） |
| `live_all.log` | **L2 live 复核 7/7**（另一批 E2E，"live 与 replay 一致"的原始日志） |

## 附注：快照一致性核查（释放前最后检查）

云端与本地 7 份快照的 `metadata.json` md5 对比：**6 份完全一致**；`checkout-pod_crash-seed42` 不一致 —— 经内容比对，差异**仅为时间戳**：云端版本是 E2E 时（2026-09-16T13:41Z）重新注入场景 001 覆盖生成，**本地版本是当日评测（T07:34Z）的原始快照（权威，勿动）**。其余字段（namespace / service_topology / services）完全一致。无数据丢失。
