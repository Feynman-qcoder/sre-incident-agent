# quote-high_latency-seed42

## 注入了什么

- 故障服务：**quote**
- 故障类型：**high_latency**（chaos_kind: NetworkChaos）
- 注入窗口：2026-09-18T07:37:11.073309+00:00 → 2026-09-18T07:44:13.804993+00:00
- seed: 42；manifest hash: `c2d7c3d591c902c6`
- 场景定义：`scenarios/mvp/?`

## 预期答案（ground truth）

| 字段 | 值 |
|---|---|
| fault_service | `quote` |
| fault_type | `high_latency` |
| validation_passed | False（见执行记录的 validation 局限说明） |

## 关键证据文件

```
  ground_truth.json
  k8s/events.json
  loki/raw_queries.json
  metadata.json
  prometheus/raw_queries.json
  tempo/trace_summaries.json
  tempo/traces/20408f5e65d805168be7d39067ce0eb1.json
  tempo/traces/37a0c46c56a28e4f1e8953aca5c3dcb3.json
  tempo/traces/4ba64e3d735f207e2620f33bbdd0d179.json
  tempo/traces/5d44555ce9f643e51c38d02e27dae90a.json
  tempo/traces/c3fb7c2d739c7fabb890084ea83b4bbb.json
```

## 演示看点

- 讲「低流量边界」：quote 0.004 req/s → p99 直方图全 NaN，比值类规则永 False。
- 讲「absent 补盲」：OtelDemoTelemetryAbsent（Pyrra 同思想）为此而生；staleness 结构（真实时延≈15 分钟）是设计级发现。
- replay 里 Agent 仍 1.000——快照中的 K8s 事件证据足够归因。
