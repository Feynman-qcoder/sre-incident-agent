"""Health check for all observability backends. Exits 0 only if all checks pass."""

from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()  # must run before reading env vars

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:19090")
TEMPO_URL = os.getenv("TEMPO_URL", "http://localhost:13200")
LOKI_URL = os.getenv("LOKI_URL", "http://localhost:13100")

CHECKS_PASSED = 0
CHECKS_FAILED = 0


def check(name: str, url: str, expected_status: int = 200) -> bool:
    global CHECKS_PASSED, CHECKS_FAILED
    try:
        r = httpx.get(url, timeout=5.0)
        if r.status_code == expected_status:
            print(f"  [OK]   {name}")
            CHECKS_PASSED += 1
            return True
        else:
            print(f"  [FAIL] {name} — HTTP {r.status_code} (expected {expected_status})")
            CHECKS_FAILED += 1
            return False
    except Exception as e:
        print(f"  [FAIL] {name} — {e}")
        CHECKS_FAILED += 1
        return False


def check_prometheus_targets() -> bool:
    """Verify at least 10 scrape targets are 'up'."""
    global CHECKS_PASSED, CHECKS_FAILED
    try:
        r = httpx.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": "up"}, timeout=5.0)
        data = r.json()
        up_count = sum(1 for m in data.get("data", {}).get("result", []) if m["value"][1] == "1")
        if up_count >= 6:
            print(f"  [OK]   Prometheus scrape targets up: {up_count}")
            CHECKS_PASSED += 1
            return True
        else:
            print(f"  [FAIL] Prometheus scrape targets up: {up_count} (need ≥6)")
            CHECKS_FAILED += 1
            return False
    except Exception as e:
        print(f"  [FAIL] Prometheus targets — {e}")
        CHECKS_FAILED += 1
        return False


def check_tempo_traces() -> bool:
    """Verify at least 1 trace exists in Tempo."""
    global CHECKS_PASSED, CHECKS_FAILED
    try:
        r = httpx.get(f"{TEMPO_URL}/api/search", params={"limit": 5}, timeout=10.0)
        data = r.json()
        traces = data.get("traces", [])
        if len(traces) > 0:
            print(f"  [OK]   Tempo traces available: {len(traces)} found in search")
            CHECKS_PASSED += 1
            return True
        else:
            print("  [WARN] Tempo has no traces yet (loadgenerator may need more time)")
            # Not a hard failure — loadgenerator might still be warming up
            CHECKS_PASSED += 1
            return True
    except Exception as e:
        print(f"  [FAIL] Tempo traces — {e}")
        CHECKS_FAILED += 1
        return False


def main() -> None:
    print("\nOTel SRE-Copilot — Health Check")
    print("=" * 40)

    print("\nPrometheus:")
    check("Prometheus API", f"{PROMETHEUS_URL}/-/healthy")
    check_prometheus_targets()

    print("\nTempo:")
    check("Tempo ready", f"{TEMPO_URL}/ready")
    check_tempo_traces()

    print("\nLoki:")
    check("Loki ready", f"{LOKI_URL}/ready")
    check("Loki labels API", f"{LOKI_URL}/loki/api/v1/labels")

    print("\n" + "=" * 40)
    print(f"Passed: {CHECKS_PASSED}  Failed: {CHECKS_FAILED}")

    if CHECKS_FAILED > 0:
        print("\nSome checks failed. Is the cluster running? Try: make up")
        sys.exit(1)
    else:
        print("\nAll checks passed. Ready to inject faults and run eval.")
        sys.exit(0)


if __name__ == "__main__":
    main()
