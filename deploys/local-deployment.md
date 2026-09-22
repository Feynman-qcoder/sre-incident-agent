# 本地部署（Local Deployment）

在本地机器上拉起完整栈（kind 集群 + 可观测三件套 + 微服务 SUT + Chaos Mesh），用于开发调试、评测跑批与离线演示。

> 只想看效果？无需部署——`make demo-offline` + 双击 `webui/index.html` 即可（见 [README](README.md) 三档门槛 ①）。

## 1. 前置依赖

| 组件 | 版本要求 | 安装 |
|---|---|---|
| Docker | 20.10+（**必须运行中**） | 安装与镜像源配置见 [docker-deployment.md](docker-deployment.md) |
| kind | 0.20+ | [kind.sigs.k8s.io](https://kind.sigs.k8s.io/docs/user/quick-start/#installation) |
| helm | 3.12+ | [helm.sh](https://helm.sh/docs/intro/install/) |
| kubectl | 1.27+ | [kubernetes.io](https://kubernetes.io/docs/tasks/tools/) |
| Python | 3.11+ | 项目使用 venv（见下） |
| 内存 | **16 GB 起**（全栈含 15 个微服务 + OpenSearch/Kafka，8 核更佳） | — |

Windows 用户请在 **WSL2** 内操作（仓库含 `scripts/wsl2_preflight.sh` 自动调优 inotify 限制，`make setup/up` 会调用）。

## 2. 步骤

```bash
# 0) 克隆并进入仓库，创建虚拟环境
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate

# 1) 配置 LLM（deploys/README.md §LLM 配置）
cp .env.example .env        # 填 NIM_API_KEY / NIM_BASE_URL / NIM_MODEL

# 2) 安装依赖 + 工具检查（含 WSL2 预检）
make setup

# 3) 拉起集群与全部组件（kind + Prometheus/Tempo/Loki/OTel Demo/Chaos Mesh）
make up                     # 首次约 20–40 分钟（镜像拉取为主），幂等可重跑

# 4) 健康检查（三后端 + 命名空间 + Pod 就绪）
make health-check           # 期望 Passed: 6  Failed: 0

# 5) 注入一个故障并采集快照（生成 ground truth）
make fault SCENARIO=scenarios/mvp/001-checkoutservice-pod-crash.yaml

# 6) 评测（11 场景 × 4 方法同 run 对照）
make eval-all
make compare                # 生成对照报告
```

采集完成后，每个快照目录应含 **12 个文件**：`DEMO.md` / `ground_truth.json` / `metadata.json` / `prometheus/raw_queries.json` / `loki/raw_queries.json` / `k8s/events.json` / `tempo/trace_summaries.json`，以及 `tempo/traces/` 下 **5 条**样例 trace——只有空目录（或缺 `ground_truth.json`）说明采集失败。

## 3. 常用操作

```bash
make help                   # 全部目标
make investigate START=... END=...   # 手工指定窗口跑一次调查
make watchdog               # 启动告警驱动值守（消费 Prometheus 告警）
make eval-replay RUN_ID=<id>         # 回放既有 run 做确定性复验
make demo-all               # 评测 + 重建前端数据（一键复现）
make down                   # 销毁 kind 集群
```

## 4. 常见问题

| 症状 | 处置 |
|---|---|
| `make up` 卡在 helm `--wait` 超时 | 多为镜像拉取排队（kubelet 串行拉取）——增大超时或预拉镜像后重跑；`make up` 幂等 |
| 端口 `9090/3200/3100` 不通 | 集群内 NodePort 未暴露；确认 values 中 service 配置生效，或见 `infra/expose-nodeports.yaml` |
| WSL2 下 inotify 报错 | `bash scripts/wsl2_preflight.sh`（`make setup/up` 已内置调用，重启 WSL 后需重跑） |
| 国内网络镜像慢/超时 | 属预期——本地部署建议配置 Docker 镜像源；云端有完整方案见 [aliyun-ecs-deployment.md](aliyun-ecs-deployment.md) |
| 评测报 `snapshot_missing` | Windows 下编码问题（UTF-8 YAML 被按 GBK 读）——设置环境变量 `PYTHONUTF8=1` 后重跑 |

> 更细的排查（含 helm/kind 配置字段层级、NodePort pin 不支持、remote_write 服务名等）见 [aliyun-ecs-deployment.md](aliyun-ecs-deployment.md) §6 坑清单——多数坑本地同样适用。
