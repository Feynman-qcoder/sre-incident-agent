# infra/calibration — P1 黄金指标阈值校准工具

从旧机 `/root/p1_calibration/` 取回（R0 阶段 git 化），供新集群校准直接复用。

## 用法（Phase A′）

```bash
# 单次采样：15 服务 × {p99_now / p99_ref(offset 30m) / ratio / error_ratio}
python3 sample_once.py > round_N.json

# 3 轮健康采样（间隔 10 分钟）
./run_health.sh          # round 1..3

# 故障期裕度采样（注入 002 后每分钟一次，第 2–7 分钟）
./run_fault_probe.sh     # fault_min_2..7.json
```

## 脚本清单

- `sample_once.py` — 核心采样器（查询与 `src/telemetry_queries.py` 同源；**PromQL offset 写法已修正为 `[5m] offset 30m`**，旧版 `rate(...[5m]) offset 30m` 是非法语法）
- `run_health.sh` / `run_health2.sh` — 多轮健康采样循环（round 1–3 / 4–6）
- `run_fault_probe.sh` — 注入场景 002 的故障期采样
- `observe30.sh` — 30 分钟观察器（每 5 分钟 load + 流量，GO/NO-GO 判据用）
- `delayed_start.sh` — 延时启动器（等待参考窗口脱离故障尾巴）

## 注意

- `sample_once.py` 的 bash 包装里轮次标记必须写 `${i}_DONE`（`$i_DONE` 会被解析为未定义变量 `i_DONE`）
- 采样有效性前提：**当前窗口与 30 分钟前参考窗口均处于健康稳态**（offset 30m 语义）
