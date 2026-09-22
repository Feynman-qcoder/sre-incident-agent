# frontend-pod_crash-seed42

## 注入了什么

- 故障服务：**frontend**
- 故障类型：**pod_crash**（chaos_kind: PodChaos）
- 注入窗口：2026-09-16T08:14:49.604059+00:00 → 2026-09-16T08:21:49.827146+00:00
- seed: 42；manifest hash: `feed1acecec8c67b`
- 场景定义：`scenarios/mvp/?`

## 预期答案（ground truth）

| 字段 | 值 |
|---|---|
| fault_service | `frontend` |
| fault_type | `pod_crash` |
| validation_passed | True（见执行记录的 validation 局限说明） |

## 关键证据文件

```
  ground_truth.json
  k8s/events.json
  loki/raw_queries.json
  metadata.json
  prometheus/raw_queries.json
  tempo/trace_summaries.json
  tempo/traces/1cb208886a18fbfdb2ab5f5a7affed93.json
  tempo/traces/6af642aac067a01f22955dee6e4bc758.json
  tempo/traces/841cbdc1465b772a5522af67c52785aa.json
  tempo/traces/afd88904d7977572474f0727aaf7a638.json
  tempo/traces/fef8710ecdeca535780909decd185681.json
```

## 演示看点

- 讲「秒级重启 < 检测粒度」（007 发现）：container-kill 的 pod 秒级恢复，pod 类规则抓不到——已知边界。
- 对比 008（pod-failure 5min 可靠触发）：故障机制选择本身就是检测设计。
