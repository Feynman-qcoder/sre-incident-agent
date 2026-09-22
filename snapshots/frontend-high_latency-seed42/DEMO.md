# frontend-high_latency-seed42

## 注入了什么

- 故障服务：**frontend**
- 故障类型：**high_latency**（chaos_kind: NetworkChaos）
- 注入窗口：2026-09-18T07:04:53.943661+00:00 → 2026-09-18T07:11:56.157277+00:00
- seed: 42；manifest hash: `fe62d6a614896431`
- 场景定义：`scenarios/mvp/?`

## 预期答案（ground truth）

| 字段 | 值 |
|---|---|
| fault_service | `frontend` |
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
  tempo/traces/3a325b33bac293cb7ef114b0bba94311.json
  tempo/traces/4e2c68a5fcf7ef5f52d1e66f364e1844.json
  tempo/traces/c37bf8483ef2c2fad4ea3a44cb254bdd.json
  tempo/traces/cdcbc5993bf8da83063a4ec97e5a202f.json
  tempo/traces/edf4d35c17d2e6d7aaddf52daad2b447.json
```

## 演示看点

- 讲「高基线服务的检测难点」：frontend 基线 p99 恒顶格 10s，1200ms 注入后相对跳变 1.0x——结构性失明。
- error_rate 只到 2.9%（<10% 阈）——两条黄金规则都不触发，是诚实零分（发现型）。
