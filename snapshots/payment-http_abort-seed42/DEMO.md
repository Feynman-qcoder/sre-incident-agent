# payment-http_abort-seed42

## 注入了什么

- 故障服务：**payment**
- 故障类型：**http_abort**（chaos_kind: NetworkChaos）
- 注入窗口：2026-09-16T07:51:35.039063+00:00 → 2026-09-16T07:58:35.271496+00:00
- seed: 42；manifest hash: `ac98e178aa69849d`
- 场景定义：`scenarios/mvp/?`

## 预期答案（ground truth）

| 字段 | 值 |
|---|---|
| fault_service | `payment` |
| fault_type | `http_abort` |
| validation_passed | True（见执行记录的 validation 局限说明） |

## 关键证据文件

```
  ground_truth.json
  k8s/events.json
  loki/raw_queries.json
  metadata.json
  prometheus/raw_queries.json
  tempo/trace_summaries.json
  tempo/traces/1a7027bbba08b46dfc2c96a2a934483d.json
  tempo/traces/1b5eac390519def954797d58bdc07e2.json
  tempo/traces/5b5a72e1fae52feca8721b5ece428ea7.json
  tempo/traces/896fe41373d5f20d516b7580f28f8598.json
  tempo/traces/e79c64ea5fb1b354cb98a00a35aadbd7.json
```

## 演示看点

- 讲「机制与元数据分离」：gRPC 服务用 NetworkChaos loss 注入，fault_type 钉在 http_abort 口径。
- 讲「记忆救场」（批次1 实测）：tool_calls 35→11、latency -33%——记忆对照卡片的素材来源。
