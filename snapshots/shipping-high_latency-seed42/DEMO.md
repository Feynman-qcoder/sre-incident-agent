# shipping-high_latency-seed42

## 注入了什么

- 故障服务：**shipping**
- 故障类型：**high_latency**（chaos_kind: NetworkChaos）
- 注入窗口：2026-09-16T08:09:46.968916+00:00 → 2026-09-16T08:16:47.199366+00:00
- seed: 42；manifest hash: `78187946839d86b3`
- 场景定义：`scenarios/mvp/?`

## 预期答案（ground truth）

| 字段 | 值 |
|---|---|
| fault_service | `shipping` |
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
  tempo/traces/41c6c856e9470ec501a55f60460bebe3.json
  tempo/traces/841cbdc1465b772a5522af67c52785aa.json
  tempo/traces/8e1b3f701d24c489732ad727d6fa2983.json
  tempo/traces/a460e38245609290fa28023a1259445c.json
  tempo/traces/fef8710ecdeca535780909decd185681.json
```

## 演示看点

- 讲「门 C 校准故事」：shipping 瞬时 4.0 倍跳变把告警阈值 R 从 2.5 推到 4.5——阈值是观察出来的不是拍出来的。
