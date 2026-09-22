"""Alert watchdog: poll Prometheus alerts and auto-trigger live investigations.

模块结构（design.md D2 — 单一职责、低耦合，出问题可按模块二分排查）：
- alerter.py — 轮询 + 白名单 + 指纹去重 + 冷却（离线可测，不打 LLM）
- mapping.py — 告警 → 调查入参（纯函数）
- runner.py  — 编排执行（唯一触碰既有 agent 接口的模块）
"""
