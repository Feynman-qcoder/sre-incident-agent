#!/usr/bin/env python3
"""am2wecom.py — Alertmanager → 企业微信群机器人中转（add-oncall-loop D2）。

一次性 nohup 脚本（云端宿主机，非常驻服务）：
- 监听 0.0.0.0:18080/alert：收 Alertmanager webhook POST → 每条告警转 markdown
  → POST 群机器人（URL 从 $WECOM_WEBHOOK_URL 读取，绝不写进代码/日志）；
- 节流：60s 滑动窗口 >18 条丢弃并记日志（企微群机器人 20 条/分钟限频兜底）；
- GET /health 探活。

用法（云端）：
    WECOM_WEBHOOK_URL=... nohup python3 /root/am2wecom.py > /root/am2wecom.log 2>&1 &
"""
import json
import os
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

PORT = 18080
WINDOW_S = 60
MAX_PER_WINDOW = 18   # 限频 20/min，留 2 条余量给链路 B（watchdog notifier 直发）

_sent_ts: deque[float] = deque()      # 节流窗口
_stats = {"received": 0, "sent": 0, "dropped_throttle": 0, "failed": 0}


def _throttle_ok() -> bool:
    now = time.time()
    while _sent_ts and now - _sent_ts[0] > WINDOW_S:
        _sent_ts.popleft()
    return len(_sent_ts) < MAX_PER_WINDOW


def _alert_to_markdown(a: dict) -> str:
    labels = a.get("labels", {}) or {}
    status = a.get("status", "firing")
    name = labels.get("alertname", "unknown")
    ns = labels.get("namespace", "")
    svc = labels.get("service_name") or labels.get("service") or labels.get("pod", "-")
    annot = a.get("annotations", {}) or {}
    summary = annot.get("summary", "")
    icon = "🔴" if status == "firing" else "🟢"
    lines = [
        f"{icon} **{name}** @ `{svc}` ({ns}) — {status}",
    ]
    if summary:
        lines.append(f"> {summary}")
    starts = a.get("startsAt", "")[:19].replace("T", " ")
    if starts:
        lines.append(f"<sub>since {starts}Z · via Alertmanager 治理（分组/抑制/静默）</sub>")
    return "\n".join(lines)


def _post_wecom(markdown: str) -> None:
    url = os.environ.get("WECOM_WEBHOOK_URL", "")
    if not url:
        raise RuntimeError("WECOM_WEBHOOK_URL not set")
    payload = json.dumps({"msgtype": "markdown", "markdown": {"content": markdown}}).encode()
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode())
        if body.get("errcode") != 0:
            raise RuntimeError(f"wecom errcode={body.get('errcode')}")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            body = json.dumps({"ok": True, "stats": _stats}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/alert":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length))
        _stats["received"] += len(data.get("alerts", []))
        sent_any = False
        for a in data.get("alerts", []):
            if not _throttle_ok():
                _stats["dropped_throttle"] += 1
                continue
            try:
                _post_wecom(_alert_to_markdown(a))
                _sent_ts.append(time.time())
                _stats["sent"] += 1
                sent_any = True
            except Exception as e:  # noqa: BLE001 — 单条失败不断链路
                _stats["failed"] += 1
                print(f"send_failed alert={a.get('labels', {}).get('alertname')} err={e!r}",
                      flush=True)
        self.send_response(200 if not _stats["failed"] or sent_any else 200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{time.strftime('%H:%M:%S')} {fmt % args}", flush=True)


if __name__ == "__main__":
    if not os.environ.get("WECOM_WEBHOOK_URL"):
        raise SystemExit("WECOM_WEBHOOK_URL not set — refusing to start")
    print(f"am2wecom relay on 0.0.0.0:{PORT} (throttle {MAX_PER_WINDOW}/{WINDOW_S}s)",
          flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
