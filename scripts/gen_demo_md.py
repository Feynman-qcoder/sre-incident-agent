"""生成 11 份 snapshots/<id>/DEMO.md 骨架（故障/参数/真值/证据文件）+ 演示看点注入。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 演示看点（批次 1 执行记录的各场景卖点提炼）
HIGHLIGHTS = {
    "checkout-pod_crash-seed42": [
        "讲「同轮去重」：KubePodNotReady 与 ReplicasMismatch 同服务同轮只查一次（P15-01 修复）。",
        "讲「K8s 事件铁证」：ImagePullBackOff 全窗口 = pod-failure 真实生效。",
        "validation FAIL 不影响快照有效性——低流量服务的 z 分数局限是已知边界。",
    ],
    "product-catalog-high_latency-seed42": [
        "讲「判别性注入」：1500ms 是从 200ms 失败教训里校准出来的（噪声基线之上才有信号）。",
        "讲「级联归因」：product-catalog 慢 → recommendation/checkout 跟着慢，Agent 正确锁定源头。",
        "这是三轮重跑里 grounding 满分的常客。",
    ],
    "payment-http_abort-seed42": [
        "讲「机制与元数据分离」：gRPC 服务用 NetworkChaos loss 注入，fault_type 钉在 http_abort 口径。",
        "讲「记忆救场」（批次1 实测）：tool_calls 35→11、latency -33%——记忆对照卡片的素材来源。",
    ],
    "recommendation-cpu_stress-seed42": [
        "讲「环境表征边界」：8 vCPU 集群里 cpu_stress 无可观测表征（004 发现）——replay 里 Agent 靠级联信号归因。",
        "三轮 1.000——发现型场景不等于评测失败，是诚实边界。",
    ],
    "cart-memory_stress-seed42": [
        "讲「内存压力信号」：working set 爬升 + OOM 边缘，memory_stress 是 A 类里最直观的资源故障。",
    ],
    "shipping-high_latency-seed42": [
        "讲「门 C 校准故事」：shipping 瞬时 4.0 倍跳变把告警阈值 R 从 2.5 推到 4.5——阈值是观察出来的不是拍出来的。",
    ],
    "frontend-pod_crash-seed42": [
        "讲「秒级重启 < 检测粒度」（007 发现）：container-kill 的 pod 秒级恢复，pod 类规则抓不到——已知边界。",
        "对比 008（pod-failure 5min 可靠触发）：故障机制选择本身就是检测设计。",
    ],
    "email-pod_crash-seed42": [
        "讲「A 类全链路」（批次1 新场景）：告警 81s → 开查 30s → top-1 精确命中 + 企微通知。",
        "pod-failure（整 pod 停 5 分钟）与 007 的 container-kill 形成对照实验。",
    ],
    "frontend-high_latency-seed42": [
        "讲「高基线服务的检测难点」：frontend 基线 p99 恒顶格 10s，1200ms 注入后相对跳变 1.0x——结构性失明。",
        "error_rate 只到 2.9%（<10% 阈）——两条黄金规则都不触发，是诚实零分（发现型）。",
    ],
    "quote-high_latency-seed42": [
        "讲「低流量边界」：quote 0.004 req/s → p99 直方图全 NaN，比值类规则永 False。",
        "讲「absent 补盲」：OtelDemoTelemetryAbsent（Pyrra 同思想）为此而生；staleness 结构（真实时延≈15 分钟）是设计级发现。",
        "replay 里 Agent 仍 1.000——快照中的 K8s 事件证据足够归因。",
    ],
    "payment-network-partition-seed42": [
        "讲「B→A 弧线」：partition 后 payment SERVER span 消失（失明），但 checkout 的 SERVER 错误率触发——调用方路径可见。",
        "CLIENT 规则（批次1 新增）因 product-catalog 数据面异常被背景误报污染——诚实降级记录。",
    ],
}

def main() -> None:
    for sdir in sorted((ROOT / "snapshots").iterdir()):
        if not sdir.is_dir():
            continue
        gt_path = sdir / "ground_truth.json"
        if not gt_path.exists():
            continue
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        meta_path = sdir / "metadata.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        sid = gt.get("scenario_id", sdir.name)
        yml = ROOT / "scenarios" / "mvp"
        yml_file = next(iter(yml.glob(f"*{sid.split('-seed')[0]}*.yaml")), None)
        ev_files = sorted(p.relative_to(sdir).as_posix() for p in sdir.rglob("*")
                          if p.is_file() and p.suffix in {".json", ".jsonl"})
        hl = HIGHLIGHTS.get(sid, ["（看点待补）"])
        lines = [
            f"# {sid}", "",
            "## 注入了什么", "",
            f"- 故障服务：**{gt.get('fault_service', '?')}**",
            f"- 故障类型：**{gt.get('fault_type', '?')}**（chaos_kind: {gt.get('chaos_kind', '?')}）",
            f"- 注入窗口：{gt.get('window_start', '?')} → {gt.get('window_end', '?')}",
            f"- seed: {gt.get('seed', 42)}；manifest hash: `{gt.get('chaos_manifest_hash', '?')}`",
            f"- 场景定义：`scenarios/mvp/{yml_file.name if yml_file else '?'}`",
            "",
            "## 预期答案（ground truth）", "",
            f"| 字段 | 值 |",
            f"|---|---|",
            f"| fault_service | `{gt.get('fault_service')}` |",
            f"| fault_type | `{gt.get('fault_type')}` |",
            f"| validation_passed | {gt.get('validation_passed')}（见执行记录的 validation 局限说明） |",
            "",
            "## 关键证据文件", "",
            "```",
        ] + [f"  {f}" for f in ev_files[:12]] + [
            "```", "",
            "## 演示看点", "",
        ] + [f"- {h}" for h in hl] + [""]
        (sdir / "DEMO.md").write_text("\n".join(lines), encoding="utf-8")
        print(f"DEMO.md: {sid}")
    print("done: 11 files")

if __name__ == "__main__":
    main()
