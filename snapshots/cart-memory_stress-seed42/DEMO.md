# cart-memory_stress-seed42

## 注入了什么

- 故障服务：**cart**
- 故障类型：**memory_stress**（chaos_kind: StressChaos）
- 注入窗口：2026-09-16T08:03:12.954977+00:00 → 2026-09-16T08:10:13.183568+00:00
- seed: 42；manifest hash: `f118f19bea7ce1c0`
- 场景定义：`scenarios/mvp/?`

## 预期答案（ground truth）

| 字段 | 值 |
|---|---|
| fault_service | `cart` |
| fault_type | `memory_stress` |
| validation_passed | True（见执行记录的 validation 局限说明） |

## 关键证据文件

```
  ground_truth.json
  k8s/events.json
  loki/raw_queries.json
  metadata.json
  prometheus/raw_queries.json
  tempo/trace_summaries.json
  tempo/traces/10d4a9bdc304de5b6bf49058506c9213.json
  tempo/traces/3467df638602d632776b4f7cec302594.json
  tempo/traces/66c7fcc1c5420d5422b573661bc2185d.json
  tempo/traces/8d298276bc98027508126d9fa6dd88.json
  tempo/traces/a80f4a569f881d51ef2984ce1a2f8c89.json
```

## 演示看点

- 讲「内存压力信号」：working set 爬升 + OOM 边缘，memory_stress 是 A 类里最直观的资源故障。
