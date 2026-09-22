# checkout-pod_crash-seed42

## 注入了什么

- 故障服务：**checkout**
- 故障类型：**pod_crash**（chaos_kind: PodChaos）
- 注入窗口：2026-09-16T07:34:41.978603+00:00 → 2026-09-16T07:41:42.217372+00:00
- seed: 42；manifest hash: `6bd9557af8fb5e98`
- 场景定义：`scenarios/mvp/?`

## 预期答案（ground truth）

| 字段 | 值 |
|---|---|
| fault_service | `checkout` |
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
  tempo/traces/24253b5cc2e552f29f9cf41a5bde473d.json
  tempo/traces/6f3f234b52a6d5dbb0a9d6db2bff1e1e.json
  tempo/traces/6ff2d557812073bb17bb720f5c47aedb.json
  tempo/traces/788786ac898c3efd8498c1736f0a3ed9.json
  tempo/traces/b14bccd5421fd537f82508e7a1d9dda0.json
```

## 演示看点

- 讲「同轮去重」：KubePodNotReady 与 ReplicasMismatch 同服务同轮只查一次（P15-01 修复）。
- 讲「K8s 事件铁证」：ImagePullBackOff 全窗口 = pod-failure 真实生效。
- validation FAIL 不影响快照有效性——低流量服务的 z 分数局限是已知边界。
