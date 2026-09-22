# email-pod_crash-seed42

## 注入了什么

- 故障服务：**email**
- 故障类型：**pod_crash**（chaos_kind: PodChaos）
- 注入窗口：2026-09-18T08:09:54.122137+00:00 → 2026-09-18T08:16:55.391337+00:00
- seed: 42；manifest hash: `727da790d6df9c83`
- 场景定义：`scenarios/mvp/?`

## 预期答案（ground truth）

| 字段 | 值 |
|---|---|
| fault_service | `email` |
| fault_type | `pod_crash` |
| validation_passed | False（见执行记录的 validation 局限说明） |

## 关键证据文件

```
  ground_truth.json
  k8s/events.json
  loki/raw_queries.json
  metadata.json
  prometheus/raw_queries.json
  tempo/trace_summaries.json
  tempo/traces/20ddd5af998125ea2527a8d1585c427b.json
  tempo/traces/3a28799d4d7f011aa4ea071d292f7f5c.json
  tempo/traces/411395fbde48fbcdce2968849286f4d6.json
  tempo/traces/670915fcf8ed986f77bf79a7951b1599.json
  tempo/traces/a9689a088cdba9045da05d61308615b9.json
```

## 演示看点

- 讲「A 类全链路」（批次1 新场景）：告警 81s → 开查 30s → top-1 精确命中 + 企微通知。
- pod-failure（整 pod 停 5 分钟）与 007 的 container-kill 形成对照实验。
