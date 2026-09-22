# 部署指南（Deployment Guide）

本项目支持两种部署形态，按你的目标选择：

| | **本地部署** | **阿里云 ECS 部署** |
|---|---|---|
| 硬件要求 | 笔记本/台式机，**16 GB 内存起**（8 核更佳） | **8 vCPU / 32 GB** 以上，**ESSD PL1 云盘 ≥100 GB** |
| 依赖 | Docker + kind + helm + kubectl | 除上述外需自行处理**国内镜像源**（已备脚本） |
| 首次耗时 | **20–40 分钟**（`make up` 首次实测，镜像拉取为主；含依赖安装视网络 30–60 分钟） | **60–90 分钟**（含镜像源配置与预拉） |
| 适用场景 | 开发调试、离线演示、跑评测 | 真实告警驱动值守（watchdog 长跑）、故障注入采集、真集群演示录屏 |
| 网络要求 | 可完全离线（`make demo-offline`，零集群零 Key） | 需出网（镜像拉取、LLM API、企微 webhook） |
| 文档 | [local-deployment.md](local-deployment.md) | [aliyun-ecs-deployment.md](aliyun-ecs-deployment.md) |

## 三档门槛（按投入从小到大）

> 环境前提：以下 Makefile 目标内部调用 `python3`，请在 **Linux / macOS / WSL2** 下执行（Windows 建议在 WSL2 内操作）；纯 PowerShell 环境可改用 `.venv\Scripts\python.exe -m <module>` 直接调用脚本。

**① 零依赖看演示**（无需集群、无需 API Key、无需安装）

```bash
# 仓库内已包含构建好的 webui/bundle.js —— 直接双击 webui/index.html 即可，四视图完整可用
# 需要从 artifacts/snapshots 重建 bundle 时（可选；唯一外部依赖 PyYAML）：
pip install pyyaml && make demo-offline
```

这不是降级方案：**replay 是设计上的一等公民**（`DataSource` 协议使快照回放与真实查询可互换），且已有 live 复核背书（同一时间窗分别查快照与真实后端，结论 7/7 一致）。

**② 回放真实告警流**（需 LLM Key）

```bash
python -m venv .venv && source .venv/bin/activate   # 首次：建虚拟环境
pip install -e .                                    # 首次：装项目依赖（tier ② 需要）
cp .env.example .env     # 填写 LLM Key（见下）
python -m scripts.watchdog --replay-alerts tests/fixtures/demo-alerts.jsonl --once
```

> 国内网络下 pip 默认源可能不可达（实测：默认源与部分公共镜像不通，**阿里云源可用**）：
> `pip install -i https://mirrors.aliyun.com/pypi/simple/ -e .`

真实录制的告警子集在笔记本上走完**告警治理链**：白名单过滤 → 指纹去重 → 服务级冷却。后端（Prometheus / Loki / Tempo）可达时继续**自动调查 → 报告落盘**；不可达时按设计跳过调查，不产生垃圾报告与无谓花费。

| 场景 | 行为 | 命令 |
|---|---|---|
| 只验证治理判定（零 LLM） | 输出 `alert_seen / alert_filtered / skipped_* / investigation_would_start` | 加 `--dry-run --no-notify` |
| 已部署本地集群（`make up`） | 走完整链路：自动调查 + 报告落盘 | 默认（不加 `--dry-run`） |

**③ 完整部署**（真实集群，端到端）→ 见下列两种部署方式

## LLM 配置（各形态通用）

```bash
# .env（变量名沿用 NIM_* 前缀，指向任意 OpenAI 兼容端点即可）
NIM_API_KEY=<your-llm-api-key>
NIM_BASE_URL=https://api.deepseek.com
NIM_MODEL=deepseek-flash
```

本项目实测选型为 `deepseek-flash`（同任务较 glm-5.3 提速 6.1×，质量不退）——成本数字均按 deepseek 官方实价口径。切换模型只需改 `.env` 三个变量，无需改代码。

## 相关文档

| 文档 | 内容 |
|---|---|
| [local-deployment.md](local-deployment.md) | 本地部署完整步骤（前置依赖 / 集群拉起 / 健康检查 / 常见问题） |
| [aliyun-ecs-deployment.md](aliyun-ecs-deployment.md) | 阿里云 ECS 部署（三种情景决策 / 镜像源纪律 / 12 项坑清单 / 成本预算） |
| [docker-deployment.md](docker-deployment.md) | Docker 的角色与配置（kind 运行时 / 两层镜像源 / 节点内校验 / Docker 侧排查） |
| [`deploys/scripts/`](scripts/) | 云端部署工具：`cloud-bootstrap.sh`（环境引导 + 镜像源）、`setup-local-helm-repo.sh`（本地 chart 仓库）、`kind-prepull.sh`（预拉镜像） |
| [`Makefile`](../Makefile) | 全部目标与用法（`make help`） |
