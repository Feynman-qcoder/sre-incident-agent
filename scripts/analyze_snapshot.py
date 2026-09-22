#!/usr/bin/env python3
"""分析 sre-incident-agent 快照：按 ground_truth 的窗口切分，判断"故障信号是否真的存在"。

背景：`make fault` 会在最后做一次 snapshot_validation，若打印
      `snapshot_validation_FAIL ... hint='faulted service is not a clear outlier'`
      它只在说"故障服务不够异常"，**不等于没采到数据**。
      本工具直接读快照里的原始查询结果，按三段（故障前 / 故障中 / 恢复后）算均值，
      给出每个指标的变化倍数 —— 用来回答两个问题：
        1) 采集本身是否有效（有没有数据）
        2) 故障期是否真的出现了可辨识的变化（信号够不够强）

用法：
    python analyze_snapshot.py <快照目录> [<快照目录> ...]
    python analyze_snapshot.py ../snapshots/*            # 一次分析全部

依赖：仅标准库。
"""

import json
import os
import sys
from datetime import datetime
from statistics import mean


def _parse_ts(text):
    return datetime.fromisoformat(text).timestamp()


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _series(entry):
    """把一条查询的所有序列拍平成 [(t, v), ...]（多序列时合并，够用于判断量级）"""
    out = []
    for s in entry.get("result") or []:
        for pair in s.get("values") or []:
            try:
                out.append((float(pair[0]), float(pair[1])))
            except (TypeError, ValueError):
                continue
    out.sort()
    return out


def _fmt(x):
    if x != x:  # NaN
        return "     n/a"
    return f"{x:11.5g}"


def analyse(snap_dir, top=None):
    snap_dir = snap_dir.rstrip("/\\")
    name = os.path.basename(snap_dir)
    print("=" * 108)
    print(f"快照 {name}")

    gt_path = os.path.join(snap_dir, "ground_truth.json")
    pq_path = os.path.join(snap_dir, "prometheus", "raw_queries.json")
    if not os.path.exists(gt_path):
        print("  !! 缺 ground_truth.json（目录不完整）")
        return None
    if not os.path.exists(pq_path):
        print("  !! 缺 prometheus/raw_queries.json（**没有采到指标数据**）")
        return None

    gt = _load(gt_path)
    pq = _load(pq_path)
    inj, rec = _parse_ts(gt["injection_ts"]), _parse_ts(gt["recovery_ts"])

    print(f"  服务={gt.get('fault_service')}  类型={gt.get('fault_type')}  "
          f"自检通过={gt.get('validation_passed')}")
    print(f"  窗口 {gt['window_start']}  →  {gt['window_end']}")
    print(f"  故障 {gt['injection_ts']}  →  {gt['recovery_ts']}")

    rows = []
    for entry in pq:
        ser = _series(entry)
        if not ser:
            continue
        pre = [v for t, v in ser if t < inj]
        mid = [v for t, v in ser if inj <= t <= rec]
        post = [v for t, v in ser if t > rec]
        if not mid:
            continue
        base = mean(pre) if pre else float("nan")
        fm = mean(mid)
        pm = mean(post) if post else float("nan")
        # 变化倍数：基线为 0 而故障期 >0 属于「全新出现的信号」（如 pod_restarts 0→3、
        # error_rate 0→0.005），必须显式标为 ∞ 并排在最前，否则会被当成 NaN 沉底 ——
        # 而 005(cart OOMKill) 正是靠这条信号通过门控的。
        if base == base and base != 0:
            ratio = fm / base
        elif base == 0 and fm > 0:
            ratio = float("inf")
        else:
            ratio = float("nan")
        rows.append({
            "q": entry.get("query", "").replace("\n", " "),
            "base": base, "mid": fm, "post": pm, "ratio": ratio,
            "max": max(mid), "min": min(mid), "n": len(ser),
        })

    if not rows:
        print("  !! raw_queries.json 里没有任何可用数据点")
        return None

    strong = [r for r in rows if r["ratio"] == r["ratio"] and (r["ratio"] < 0.5 or r["ratio"] > 2)]
    zeros = [r for r in rows if r["ratio"] == r["ratio"] and r["max"] == 0 and r["base"] == 0]

    print(f"  查询条数={len(rows)}  其中「故障期变化 >2x 或 <0.5x」的有 {len(strong)} 条"
          f"（另有 {len(zeros)} 条恒为 0，一般不携带信息）")
    def _sort_key(x):
        r = x["ratio"]
        if r != r:                      # NaN（基线为 0 或缺失）排最后
            return (1, 0.0)
        return (0, -abs(r - 1))         # 变化倍数越偏离 1 越靠前

    shown = sorted(rows, key=_sort_key)
    if top:
        shown = shown[:top]
    print("  " + "-" * 104)
    print("   变化倍数   故障前均值      故障中均值      恢复后均值      故障中峰值")
    for r in shown:
        flag = ""
        if r["ratio"] == r["ratio"]:
            if r["ratio"] < 0.5:
                flag = " ↓↓"
            elif r["ratio"] > 2:
                flag = " ↑↑"
        print(f"  {_fmt(r['ratio'])}{flag} {_fmt(r['base'])} {_fmt(r['mid'])} "
              f"{_fmt(r['post'])} {_fmt(r['max'])}")
        print(f"        {r['q'][:150]}")

    return {"name": name, "queries": len(rows), "strong": len(strong), "zeros": len(zeros)}


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    top = None
    for a in argv[1:]:
        if a.startswith("--top="):
            try:
                top = int(a.split("=", 1)[1])
            except ValueError:
                pass
    if not args:
        print(__doc__)
        return 2
    summary = []
    for d in args:
        if not os.path.isdir(d):
            print(f"!! 不是目录：{d}")
            continue
        r = analyse(d, top=top)
        if r:
            summary.append(r)

    if len(summary) > 1:
        print("=" * 108)
        print("汇总")
        print(f"  {'快照':<45}{'查询数':>8}{'>2x/<0.5x':>12}{'恒0':>8}")
        for r in summary:
            print(f"  {r['name']:<45}{r['queries']:>8}{r['strong']:>12}{r['zeros']:>8}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
