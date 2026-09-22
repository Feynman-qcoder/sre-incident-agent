# product-catalog-high_latency-seed42

## 注入了什么

- 故障服务：**product-catalog**
- 故障类型：**high_latency**（chaos_kind: NetworkChaos）
- 注入窗口：2026-09-16T07:46:32.629994+00:00 → 2026-09-16T07:53:32.849172+00:00
- seed: 42；manifest hash: `4eba294c47744e7b`
- 场景定义：`scenarios/mvp/?`

## 预期答案（ground truth）

| 字段 | 值 |
|---|---|
| fault_service | `product-catalog` |
| fault_type | `high_latency` |
| validation_passed | True（见执行记录的 validation 局限说明） |

## 关键证据文件

```
  ground_truth.json
  k8s/events.json
  loki/raw_queries.json
  metadata.json
  prometheus/raw_queries.json
  tempo/trace_summaries.json
  tempo/traces/12d5518447e845703a02c925f5669ade.json
  tempo/traces/2c89cdfe4fb32c785c12e792f6fcdd95.json
  tempo/traces/595799059e8fd4cfe9ea4126002d7216.json
  tempo/traces/6164e53e06e28cd55f5d0a116f0cd720.json
  tempo/traces/bde63ac921a83aca6ac963e532a82e23.json
```

## 演示看点

- 讲「判别性注入」：1500ms 是从 200ms 失败教训里校准出来的（噪声基线之上才有信号）。
- 讲「级联归因」：product-catalog 慢 → recommendation/checkout 跟着慢，Agent 正确锁定源头。
- 这是三轮重跑里 grounding 满分的常客。
