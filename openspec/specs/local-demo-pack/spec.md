# local-demo-pack Specification

## Purpose
本地演示包：零集群零后端的完整演示能力——一键复现评测、前端四视图、watchdog 离线演示。**设计原则（硬性）**：证据优先于结论（P1）/ 诚实是卖点（P2，幻觉告警不折叠）/ 一个屏幕一件事（P3）/ 离线优先（P4，无 Key 无集群可完整演示）。

## Requirements

### Requirement: 一键复现

系统 SHALL 提供 `make demo-all`：单命令完成 7 场景 replay 评测（同 run 四方法）并输出演示就绪的对照表（终端表格 + `results/baseline_comparison.md` 更新）。跑批须复用 `eval-all` 既有入口（不重复实现）；产物落 `artifacts/<新 run_id>/`，**不触碰历史 runs**。`make demo-all --offline`（或等价开关）SHALL 支持纯离线模式：跳过 LLM 调用，仅渲染既有最新 run 的对照表与四视图数据（演示现场无网络/不想花钱时可用）。

#### Scenario: 一条命令完成复现

- **WHEN** 在仓库根目录执行 `make demo-all`（快照齐全、`.env` 配置 deepseek）
- **THEN** 单命令产出 7 场景四方法对照（agent + 3 基线同 run）、更新 baseline_comparison.md、并重建 webui 的数据 bundle

#### Scenario: 离线模式不烧钱

- **WHEN** 无网络/无 API Key 环境执行离线模式
- **THEN** 不发起任何 LLM 调用，界面以最近一次 run 的既有产物完整可用（P4 原则）

### Requirement: 前端四视图

系统 SHALL 提供纯静态前端（`webui/`，零后端零运行时依赖，双击 `index.html` 可开）：**构建期聚合脚本**扫描 `artifacts/`+`snapshots/`+`scenarios/` 产出 `webui/bundle.json`（唯一数据源），四个视图按既定规格实现——① 调查台（场景选择 → Top-3 假设 + 置信度 + 修复建议）② 证据追溯（tool_calls 时间线逐条可查，**每条结论可展开原始工具调用**——P1）③ 评测看板（四方法对照 + 3 轮 seed 复现 + grounding 逐场景，**幻觉告警固定展示不可折叠**——P2）④ 场景与产物（11 场景清单 + DEMO.md 内容 + chaos 参数）。**ground truth 默认遮蔽**（右上角"显示真值"点击展开），美学遵循"技术审计手册"方向（暖灰纸感/等宽字体/0.5px 规则线，禁深色监控大屏风）。

#### Scenario: 双击即开零依赖

- **WHEN** 断网状态下双击 webui/index.html
- **THEN** 四视图全部可用（数据来自构建期 bundle.json），无控制台报错、无外部请求

#### Scenario: 结论回溯到原始调用

- **WHEN** 在调查台点击任一根因假设的"查看证据"
- **THEN** 展开该假设引用的工具调用原文（query/结果摘要/耗时），且 gateway 审计信息（verdict=ALLOW/CLAMP）随附展示

#### Scenario: 诚实原则的强制展示

- **WHEN** 打开评测看板
- **THEN** grounding<0.80 的场景行带显式告警标记且不可折叠隐藏；三轮 seed 对照（1.000±0.000）与基线确定性断言结果同时可见

### Requirement: watchdog 离线演示

watchdog CLI SHALL 支持 `--replay-alerts <alerts.jsonl>`：从文件读入**真实录制的告警流**（来源 `artifacts/oncall-e2e-cloud/` 的告警事件），按时间轴回放给过滤/去重/调查全链路——笔记本无集群演示"告警 → 自动开查 → 报告落盘"。回放模式 SHALL 独立于 Prometheus 轮询（不查询真实端点）；告警流时间戳保留原始相对时序。**演示含记忆对照桥段**：payment 场景 off/on 双跑的 tool_calls 对照（35→11）作为"记忆价值"的可视化素材。

#### Scenario: 无集群演示告警驱动调查

- **WHEN** 笔记本上执行 `python -m scripts.watchdog --replay-alerts fixtures/demo-alerts.jsonl --once`（.env 配置 deepseek）
- **THEN** 白名单过滤 → 指纹/服务去重 → investigation_started → 报告 JSON 落盘全链路走通（真实 LLM 调查，~$0.003/次）；返回码 0

#### Scenario: 去重逻辑在回放中同样生效

- **WHEN** 回放流中含同服务多条告警（001 实录形态：NotReady + ReplicasMismatch 同轮）
- **THEN** 同轮去重（reason=same_cycle）与跨轮冷却在回放中行为与 live 一致（复用同一 process() 代码路径）

### Requirement: 演示材料与场景就绪化

仓库 SHALL 含每场景 `snapshots/<id>/DEMO.md`（11 份：注入故障与参数/预期答案/真实 ground truth/关键证据文件指引），且演示话术 MUST 遵守既有边界：可说"真实故障的冻结回放 + live 复核背书"，禁说"实时监控/自动修复"。

#### Scenario: 陌生人照文档可完成演示

- **WHEN** 按演示说明从零操作（开 webui → 切场景 → 展开证据 → 放离线回放 → 收尾一句话）
- **THEN** 每一步都有明确的命令/点击指引与预期画面描述，无未定义动作
