# recommendation-cpu_stress-seed42

## 注入了什么

- 故障服务：**recommendation**
- 故障类型：**cpu_stress**（chaos_kind: StressChaos）
- 注入窗口：2026-09-16T07:56:38.043393+00:00 → 2026-09-16T08:03:38.269881+00:00
- seed: 42；manifest hash: `b8f3b45cd11bad4d`
- 场景定义：`scenarios/mvp/?`

## 预期答案（ground truth）

| 字段 | 值 |
|---|---|
| fault_service | `recommendation` |
| fault_type | `cpu_stress` |
| validation_passed | True（见执行记录的 validation 局限说明） |

## 关键证据文件

```
  ground_truth.json
  k8s/events.json
  loki/raw_queries.json
  metadata.json
  prometheus/raw_queries.json
  tempo/trace_summaries.json
  tempo/traces/4bd242107089e807576a6f5b712a64b9.json
  tempo/traces/89e99b68e9c9bf65eb3d9f815924676.json
  tempo/traces/a4c77127c05db0d1ff75ed8abcfedae0.json
  tempo/traces/a6af4d21d58705f31341924b8eec9b7.json
  tempo/traces/a9f4434254b98c233c4c2775d3a10639.json
```

## 演示看点

- 讲「环境表征边界」：8 vCPU 集群里 cpu_stress 无可观测表征（004 发现）——replay 里 Agent 靠级联信号归因。
- 三轮 1.000——发现型场景不等于评测失败，是诚实边界。
