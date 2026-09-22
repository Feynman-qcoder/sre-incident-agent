# 运维经验沉淀（人工经验层）

> 本文件是 incident-memory 的人工经验层：条目在检索命中时**优先于 AI 自动记录**注入 Agent 上下文。
> 格式约定：每条一个 `## ` 块，行内含 `service: <名>` 与 `fault_type: <类型>` 标记（精确匹配检索键）。
> 来源：本人 2026-09 期间在 otel-demo 集群上的真实踩坑与复盘（每条结论都有实测证据）。

## 网络层故障不落 SERVER span——从调用方查

service: payment
fault_type: http_abort

Chaos Mesh 在网络层掐断响应（http_abort / network partition）时，受击服务的 SERVER span **正常结束、无错误标记**——错误率规则对这类故障天然失明，top-1 容易归因到级联症状服务。正确查法：直接看**调用方**（frontend/checkout 等）的 CLIENT span 延迟与错误、以及受击服务的 p99 是否饱和（实测 payment 被 abort 时其自身 p99 顶格 10000ms 无 ERROR）。若 p99 也无异常，查该服务是否压根没有 span 产生（可能已被网络分区隔离）。

## load 高先看 wa 与 r_await，再谈 CPU 核数

service: recommendation
fault_type: cpu_stress

单节点 kind 集群 load 23–40 时，先跑 `vmstat 1 5` 看 wa 列、`iostat -x 1 5` 看 r_await 与 %util——本次根因是**单块系统盘 I/O 饱和**（wa 68–75%、r_await 65ms、%util 63–73%，load 里 20+ 个是 D 状态进程），而 CPU 只有 8 vCPU 但 %steal=0 且使用率不高。教训：`lscpu` 的 "Core(s) per socket" 不是 vCPU 数（要看 CPU(s) 行）；load 高 ≠ 核数不够。云盘 PL0 升 PL1 后 wa 归零、load 0.3–0.7，问题消失。

## 秒级容器重启低于检测粒度——pod 类演示与验证用慢重启场景

service: frontend
fault_type: pod_crash

frontend 这类镜像已缓存的服务，PodChaos 容器-kill 后 ReplicaSet **秒级**拉起新副本，NotReady 窗口 < kube-state-metrics 的 30s 采集周期——两次注入均零告警（快门拍不到）。同型故障在 checkout 上能被抓到（重启恰好慢一点）。经验：演示或验证 pod 类告警链路时选 checkout 场景；对"零触发"先查故障是否真的产生了可采样的状态窗口（`kubectl get pods -w` 看重启间隙），不要先怀疑告警规则。

## 高基线服务的"慢上加慢"测不出——相对跳变规则的天花板

service: frontend
fault_type: high_latency

frontend 的健康 p99 本来就顶格在 ~10000ms（bucket 上限），对其注入 1200ms 网络延迟后 p99 与参考窗口几乎相同（ratio ≈ 1.0x）——相对跳变规则（>4.5x）对高基线服务**结构性失明**，错误率也只从 0 升到 2.9%（<10% 阈值）。经验：对入口类高基线服务，相对跳变规则不适用，需 SLO 燃烧率语义（错误预算消耗速率）或绝对阈值；排查此类"注入成功但零告警"时先对比当前 p99 与历史基线是否本来就同档。

## 低流量服务直方图无样本——先确认有数据再算比值

service: quote
fault_type: high_latency

quote 流量 ~0.004 req/s（一小时十几个请求），注入 1500ms 延迟后 spanmetrics 直方图 bucket 几乎无样本、histogram_quantile 全 NaN——任何基于 rate()/比值的规则都无数据可算。经验：对低流量服务，比值类告警天然失效；可用 absent_over_time 做数据缺席告警（注意真实触发时延 = Prometheus staleness(5m) + absent 窗口，10m 窗口实际是 ≥15 分钟断流检测）；调查时若某服务指标全空，先查流量量级再怀疑管道故障。

## 测试污染生产记忆库——副作用型写入必须目录级隔离

service: any
fault_type: any

单测里的 stub 调查若与生产共用同一写目录，writer 的"同 incident_id 覆盖"语义会把 stub 假报告覆盖真实记忆——实测 15 份真实记忆被 "fixture stub hypothesis" 覆盖，且**每次跑全量 pytest 重复发生**（污染存活两天，因无人例行查看 working tree）。三条铁律：① conftest 加 autouse fixture 把 INCIDENT_MEMORY_DIR 隔离到 tmp_path；② **monkeypatch.setenv 对 import 时求值的模块级常量无效**（MEMORY_DIR/INCIDENTS_DIR/NOTES_PATH/INDEX_PATH 均为模块级 Path，首版仅 setenv 时污染 15→2 仍发生）——必须同时 setattr 四常量；③ 跑测后例行 `git status`——副作用型写入的污染不会让任何测试变红，只能靠工作区检查发现。诊断指纹：记忆文件的 created_at 时间戳恰为 pytest 运行时刻、source_report 出现 `(in-memory:...)` 即为测试污染。
