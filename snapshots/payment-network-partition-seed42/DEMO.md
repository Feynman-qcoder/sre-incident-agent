# payment-network-partition-seed42

## 注入了什么

- 故障服务：**payment**
- 故障类型：**http_abort**（chaos_kind: NetworkChaos）
- 注入窗口：2026-09-18T07:55:42.322114+00:00 → 2026-09-18T08:02:43.605304+00:00
- seed: 42；manifest hash: `e05802af21461d0b`
- 场景定义：`scenarios/mvp/?`

## 预期答案（ground truth）

| 字段 | 值 |
|---|---|
| fault_service | `payment` |
| fault_type | `http_abort` |
| validation_passed | False（见执行记录的 validation 局限说明） |

## 关键证据文件

```
  ground_truth.json
  k8s/events.json
  loki/raw_queries.json
  metadata.json
  prometheus/raw_queries.json
  tempo/trace_summaries.json
  tempo/traces/23c5af7484cec0f99a6a94b652948cc.json
  tempo/traces/82c38c4c87fe75bbc3d653340c0fe814.json
  tempo/traces/d6a3f1eb2100f643c83f2acdcd40f25b.json
  tempo/traces/deae740737c2bd01a1be56f758036fe9.json
  tempo/traces/f5521323c4f44719223218daeab6be13.json
```

## 演示看点

- 讲「B→A 弧线」：partition 后 payment SERVER span 消失（失明），但 checkout 的 SERVER 错误率触发——调用方路径可见。
- CLIENT 规则（批次1 新增）因 product-catalog 数据面异常被背景误报污染——诚实降级记录。
