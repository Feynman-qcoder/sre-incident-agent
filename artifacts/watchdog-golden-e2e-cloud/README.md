# P1 golden-signals E2E 证据包（新环境重建后，2026-09-17）

- reports/：watchdog 自动调查报告（含 P0 遗留 3 份 20260916T13* + 本次 20260917T* 共 15+ 份 + state.json 各场景终态）
- scenario_logs/：七场景 watchdog 日志（s001/s007/s007r2/s002/s003/s006/s004/s005）+ 注入日志 + 事件摘要 + progress
- calibration/：门 A 校准原始数据（round_1..3 + fault_min_2..7 + observe 日志）
- k8s_after.txt：七场景后 deployments/pods 状态（零变更核查用）

场景执行时间线（UTC）：s001 09:49 / s007 10:04 / s007r2 10:22 / s002 10:38 / s003 10:56 / s006 11:14 / s004 11:28 / s005 11:46
