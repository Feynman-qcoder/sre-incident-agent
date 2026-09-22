# P1 七场景 E2E 证据包 — deepseek-flash 口径（2026-09-17）

- run 信息：模型 deepseek-flash（NIM_BASE_URL=api.deepseek.com）、2026-09-17 21:52–22:55 CST、协议 = P1 重建任务书 §8 + P1.5 修复（D-P1-01 cycle-local）
- reports/：本 run 的 15 份调查报告 + state.json（20260916T13* 的 P0 遗留已剔除）
- scenario_logs/：七场景日志（s001/s007/s002/s003/s006/s004/s005）+ 事件摘要 + progress
- k8s_after.txt：零变更核查快照
- 对照：glm-5.3 口径证据在 artifacts/watchdog-golden-e2e-cloud/（勿覆盖，两者并存）
- 已知口径：报告 cost_usd 走 llama 价目表（缺陷③，与 glm run 同口径可比；deepseek 实际花费更低）
