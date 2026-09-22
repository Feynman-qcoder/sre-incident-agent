# evaluation-methodology Specification

## Purpose
评测方法学核心约束：**Agent 与 baseline 的任何指标对比 MUST 出自同一 run**（同 run_id、同快照集、同 seed）——这是"可复现评估"主张成立的最低条件。消除现状：`make eval` 与 `make eval-baselines` 产出的跨 run 对比在方法学上不可辩护（快照加载路径、环境、代码版本无同一性保证）。

## Requirements

### Requirement: 同 run 全方法评测入口

系统 SHALL 提供单一命令入口 `make eval-all`（内部 `eval.scenario_runner --mode all`）：在同一 run_id 下对每个场景**先跑 agent 调查、后对同一 ReplayDataSource 实例跑全部 3 条 baseline**（random / zscore / composite_zscore），并将 4 方法的逐场景结果合并写入**单份** `artifacts/<run_id>/raw_results.json`。同 run 的定义 = 同 run_id + 同快照集 + 同 seed（`RANDOM_SEED`）；不要求墙钟同一秒。

#### Scenario: eval-all 产出四方法齐备的 run

- **WHEN** 执行 `make eval-all`（7 场景快照齐全、`NIM_MODEL` 已配置）
- **THEN** 产出的 `raw_results.json` 中每个场景条目同时含 `agent`、`random`、`zscore`、`composite_zscore` 四个键，且 agent 与 baseline 消费**同一快照目录**（`snapshot_dir` 字段一致）

#### Scenario: compare 表不再有缺失方法行

- **WHEN** 对 eval-all 产出的 run 执行 `make compare`（`eval.compare`）
- **THEN** 对比表 4 个方法行全部有数值，无 "—" 占位；表写入 `results/baseline_comparison.md`

#### Scenario: 既有单模式入口行为不变

- **WHEN** 执行 `make eval`（仅 agent）或 `make eval-baselines`（仅基线）
- **THEN** 行为与既有完全一致（各自独立 run、互不含对方结果）——旧入口与历史 runs 不受本变更影响

### Requirement: 对比口径可追溯

对比表及 `raw_results.json` MUST 携带使结果可追溯的最小口径信息：模型名（来自 `NIM_MODEL` 环境变量）、随机种子（`RANDOM_SEED`）、run_id。**latency/cost 对比 MUST 钉死模型口径**——跨模型的 latency/cost 数字不可直接比较（实测：同任务 glm-5.3 85.2s vs deepseek-flash 13.9s）。baseline 行的 latency_s / cost_usd 恒为 0 属**口径而非缺失**（纯计算方法、无 LLM 调用），表 Notes MUST 注明。

#### Scenario: 表头口径三要素

- **WHEN** 查看 eval-all run 的 `results/baseline_comparison.md`
- **THEN** Notes 区含 Model（如 deepseek-flash）、Seed（如 42）、run_id 三项，且注明 baseline 的 0 延迟/0 成本为口径约定

#### Scenario: 跨 run 对比被防呆拦截

- **WHEN** 对一个仅含 agent（或仅含 baselines）的历史 run 执行 `make compare`
- **THEN** compare 正常渲染可用行（向后兼容），但显式打印提示："此 run 缺失 N 个方法，完整对比请使用 make eval-all 产出的同 run"

### Requirement: 历史数据不可拼接

历史 runs（跨 run 的 agent / baselines 产物）MUST 原样保留，禁止任何形式的**事后合并拼接**为"同 run"数据——拼接数据无法重建同一性保证，其存在本身就会污染可复现主张。新的合法对比数据**只能**来自 `make eval-all` 的新 run。

#### Scenario: 历史单模式 run 保持原样

- **WHEN** 本变更实施完成
- **THEN** `artifacts/20260916T084825Z`（仅基线）与 `artifacts/20260916T101856Z`（仅 agent）等历史目录内容与文件名零改动；历史跨 run 对照表保留，但其方法学局限已在变更记录中备案
