# add-oncall-loop E2E 证据包（2026-09-18 12:57–13:25）

- oc_e2e_wd.log：watchdog 全程日志（alert_seen×5+KubePodNotReady、same_cycle 拦截、investigation_complete×6、**notification_sent×6**）
- oc_e2e_inject.log：001 注入日志
- am2wecom.log：中转日志（POST /alert ×5+，stats 9/9）
- ack_log.json + 20260918T04*.json：ack 留痕（incident watchdog-KubePodNotReady-3d474e83，by demo，回写 3 报告）
- am_status.txt / k8s_after.txt：零变更核查
- 企微群截图（2 张）由用户提供，事件时间：12:45 门 B 测试告警 / 12:58-13:02 诊断消息×6 / 13:12 原生告警组
- 静默演示：silence 6bfeb7bf 13:14-13:18 窗口（suppressed→expired→active，13:23 送达）
- 环境注：宿主机 11:21 意外重启（非本变更所致），CPU 风暴余波产生 5 条真实延迟告警（被 watchdog 全部正确调查并通知——额外的真实世界验证）
