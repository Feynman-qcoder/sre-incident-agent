"""Compare agent vs baselines across all metrics.

Reads the latest (or specified) run artifacts and prints a comparison table.
Generates results/baseline_comparison.md.

Usage:
    python -m eval.compare
    python -m eval.compare --run-id 20240115T143000Z
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_ARTIFACTS_DIR = Path("artifacts")
_RESULTS_DIR = Path("results")

_METRIC_HEADERS = [
    ("Acc@1", "accuracy_at_1"),
    ("Acc@3", "accuracy_at_3"),
    ("MRR", "mrr"),
    ("FT Acc", "fault_type_correct"),
    ("Grounding", "grounding_score"),
    ("Latency(s)", "latency_s"),
    ("Cost($)", "cost_usd"),
]

_METHODS = ["random", "zscore", "composite_zscore", "agent"]


def load_results(run_id: str) -> dict[str, list[dict]]:
    """Load per-scenario results for all methods from a run."""
    raw_path = _ARTIFACTS_DIR / run_id / "raw_results.json"
    if not raw_path.exists():
        raise FileNotFoundError(f"No raw_results.json for run_id={run_id}")

    with open(raw_path) as f:
        raw = json.load(f)

    methods: dict[str, list[dict]] = {m: [] for m in _METHODS}
    for scenario in raw:
        if "error" in scenario:
            continue
        for method in _METHODS:
            if method in scenario:
                methods[method].append(scenario[method])

    return methods


def aggregate(results: list[dict]) -> dict[str, float]:
    if not results:
        return {}
    n = len(results)
    out = {}
    for _, key in _METRIC_HEADERS:
        vals = [r.get(key, 0.0) for r in results]
        if key == "cost_usd":
            out[key] = sum(vals)
        else:
            out[key] = sum(vals) / n
    return out


def render_table(aggregated: dict[str, dict[str, float]]) -> str:
    headers = ["Method"] + [h for h, _ in _METRIC_HEADERS]
    col_widths = [max(len(h), 18) for h in headers]
    col_widths[0] = 22

    def row(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(cells)) + " |"

    sep = "|-" + "-|-".join("-" * col_widths[i] for i in range(len(headers))) + "-|"

    lines = [row(headers), sep]
    method_labels = {
        "random": "Random",
        "zscore": "Z-score error_rate",
        "composite_zscore": "Composite Z-score",
        "agent": "**SRE-Copilot**",
    }
    for method in _METHODS:
        agg = aggregated.get(method, {})
        if not agg:
            lines.append(row([method_labels.get(method, method)] + ["—"] * len(_METRIC_HEADERS)))
            continue

        cells = [method_labels.get(method, method)]
        for _, key in _METRIC_HEADERS:
            v = agg.get(key, 0.0)
            if key == "cost_usd":
                cells.append(f"${v:.4f}")
            elif key == "latency_s":
                cells.append(f"{v:.1f}s")
            else:
                cells.append(f"{v:.3f}")
        lines.append(row(cells))

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare agent vs baselines")
    parser.add_argument("--run-id", default="", help="Run ID to compare (default: latest)")
    args = parser.parse_args()

    # Find run_id
    if args.run_id:
        run_id = args.run_id
    else:
        dirs = sorted(_ARTIFACTS_DIR.iterdir(), reverse=True)
        run_id = next(
            (d.name for d in dirs if (d / "raw_results.json").exists()), None
        )
        if not run_id:
            print("No eval runs found. Run: make eval && make eval-baselines")
            sys.exit(1)

    print(f"\nComparing run: {run_id}")
    methods = load_results(run_id)

    # fix-eval-cross-run D4：缺失方法提示（不硬失败——历史 run 照常可渲染）
    present = [m for m in _METHODS if methods[m]]
    missing = len(_METHODS) - len(present)
    if missing:
        print(f"此 run 缺失 {missing} 个方法，完整对比请使用 make eval-all 产出的同 run")

    aggregated = {method: aggregate(results) for method, results in methods.items()}

    table = render_table(aggregated)
    print("\n" + table + "\n")

    # Write to results/
    _RESULTS_DIR.mkdir(exist_ok=True)
    with open(_RESULTS_DIR / "baseline_comparison.md", "w") as f:
        f.write(f"# Baseline Comparison — run: {run_id}\n\n")
        f.write(table)
        f.write("\n\n## Notes\n")
        f.write(f"- Run ID: {run_id}\n")
        f.write(f"- Model: {os.getenv('NIM_MODEL', 'deepseek-flash')}\n")
        f.write(f"- Seed: {os.getenv('RANDOM_SEED', '42')}\n")
        f.write("- Baseline latency/cost 恒为 0 属口径约定（纯计算、无 LLM），非缺失\n")
        f.write("- Grounding score: fraction of evidence items verified against tool_calls_log\n")
        f.write("- Random baseline grounding_score=0.0 by design (no evidence items)\n")
        if missing:
            f.write(f"- ⚠️ 此 run 缺失 {missing} 个方法（跨 run 对比方法学不成立）\n")
        f.write("- Reproduce: `make eval-replay RUN_ID=" + run_id + "`\n")

    print("Written to: results/baseline_comparison.md")


if __name__ == "__main__":
    main()
