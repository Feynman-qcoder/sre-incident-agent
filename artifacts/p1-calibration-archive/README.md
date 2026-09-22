# p1-calibration-archive（旧机污染数据存档）

> **来源**：旧机（ESSD PL0 时期，磁盘 I/O 饱和根因确诊前）`/root/p1_calibration/`，2026-09-17 R0 阶段取回（tar md5 `df2d435fa51788e7fb80286e882cb432`）。

## ⚠️ 禁止用于 R 计算

本目录全部数值数据产生于**病态环境**（宿主机两次干净关机、CoreDNS 停摆、load-generator browser VU 重试风暴、load 20–40、磁盘 r_await 65ms），仅作事故证据保留（P1 任务书红线：任何数值不得进入阈值 R 的推导）：

- `round_1..6.json`：6 轮健康期采样——无一轮同时满足"当前与 30m 参考窗口均健康"（round 1/2 参考窗口被 DNS 故障尾巴污染，round 2 比值爆炸 recommendation 686x；round 3–6 被 load 风暴打断）
- `sanity.json`：脚本 offset 修正后的 sanity 采样（仍处故障期）
- `observe.log`：GO/NO-GO 试探 30 分钟观察（7 点，load 23–40 不回落 → NO-GO 判定证据）
- `progress.log` / `*.log`：采样器运行记录

## 从污染数据中仍成立的两个确定性结论（与数值无关）

1. **近零基线比值爆炸**（round 2：recommendation 686x、product-catalog 90x）——证明延迟规则必须含"参考窗口 p99 > 100ms 才参与比值"保护条款（已固化进 spec）
2. **旧机 frontend 健康期错误基线 ≈4.4%**（browser VU 时代）——禁 browser 后须在新环境复测（spec MUST 条款，见新机校准记录）

事故全链路见项目过程记录（§〇 事故时间线 + §〇′ NO-GO 试探；过程记录为本地私有文档，未随仓库分发）。
