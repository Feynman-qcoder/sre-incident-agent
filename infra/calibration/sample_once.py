import datetime
import json
import subprocess


def q(expr):
    r = subprocess.run(
        ["curl", "-s", "--max-time", "25", "-G", "http://localhost:9090/api/v1/query",
         "--data-urlencode", "query=" + expr],
        capture_output=True, text=True,
    )
    try:
        d = json.loads(r.stdout)
        if d.get("status") != "success":
            return {"__error__": d.get("error", "unknown")[:200]}
        return {x["metric"].get("service_name", "?"): x["value"][1] for x in d["data"]["result"]}
    except Exception as e:
        return {"__error__": str(e)[:200]}


P99_NOW = "histogram_quantile(0.99, sum by (service_name, le) (rate(duration_milliseconds_bucket{span_kind=\"SPAN_KIND_SERVER\"}[5m])))"
P99_REF = "histogram_quantile(0.99, sum by (service_name, le) (rate(duration_milliseconds_bucket{span_kind=\"SPAN_KIND_SERVER\"}[5m] offset 30m)))"
RATIO = P99_NOW + " / " + P99_REF
ERR = "sum by (service_name) (rate(calls_total{span_kind=\"SPAN_KIND_SERVER\",status_code=\"STATUS_CODE_ERROR\"}[5m])) / sum by (service_name) (rate(calls_total{span_kind=\"SPAN_KIND_SERVER\"}[5m]))"

out = {
    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "p99_now_ms": q(P99_NOW),
    "p99_ref_ms": q(P99_REF),
    "ratio": q(RATIO),
    "error_ratio": q(ERR),
}
print(json.dumps(out, indent=1))
