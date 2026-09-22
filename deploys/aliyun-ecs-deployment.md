# 阿里云 ECS 部署（Aliyun ECS Deployment）

在阿里云 ECS 上部署完整栈，用于真实告警驱动值守（watchdog 长跑）、故障注入采集与真集群演示。**本方案全部步骤基于 2026-09 的完整实战（累计 17 个环境级坑，§6 精选其中可复用的 12 项），结论均为实测。**

## 1. 实例规格（实测结论）

| 项 | 要求 | 依据 |
|---|---|---|
| vCPU / 内存 | **8 vCPU / 32 GB**（`ecs.g7a.2xlarge` 或同级通用型） | 单节点需承载 15 微服务 + OpenSearch/Kafka + Prometheus/Tempo/Loki + Chaos Mesh |
| **系统盘** | **ESSD PL1，≥100 GB** | ⚠️ **PL0 会 I/O 饱和**：实测 `%wa` 68–75%、`r_await` 65 ms、队列 166、load 26–40（容量仅用 22%）——**瓶颈是磁盘性能而非 CPU 核数**；升 PL1 后 `%wa`→0、load 0.3–0.7 |
| 操作系统 | Ubuntu 22.04 / Alibaba Cloud Linux 3 | — |
| 网络 | 出网正常即可（**无需开入方向端口**；所有访问走 localhost / SSH） | 只需出方向 443（镜像源、LLM API、企微 API） |

> **诊断口诀（写进坑清单第 1 条的理由）**：load 高先跑 `vmstat 1 5` 看 `wa`、`iostat -x 1 5` 看 `r_await`/`%util`——不要先怀疑核数。另注意 `lscpu` 的 `Core(s) per socket` 不是 vCPU 数（要看 `CPU(s):` 行；8 vCPU = 4 物理核 × SMT）。

## 2. 三种情景（先判断，少走弯路）

```
打开 ECS 控制台
  ├─ 实例不存在？ ──→ 情景 C：从零开始（§4，60–90 分钟）
  ├─ 实例在、集群不在？ ──→ 情景 B：重建集群（§5，约 25 分钟）
  └─ 实例与集群都在？ ──→ 情景 A：最快路径（§3，仅需重启本地 chart 仓库）
```

判据：
```bash
docker ps --format '{{.Names}}' | grep control-plane   # 集群在否
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8879/index.yaml  # 本地 chart 仓库（HTTP 200 为正常）
```

## 3. 情景 A：实例与集群都在（最快，~55–70 分钟，其中约 50 分钟是采集本身）

```bash
# 0) 30 秒体检：节点 + 本地 chart 仓库（python http.server 不会自启，每次重启实例都会掉）
kubectl get nodes
bash /root/setup-local-helm-repo.sh          # 恢复 127.0.0.1:8879 本地 chart 仓库

# 1) 三后端健康
curl -s localhost:9090/-/healthy && curl -s localhost:3200/ready && curl -s localhost:3100/ready

# 2) Pod 就绪核查（otel-demo 与 chaos-mesh 两个命名空间）
kubectl -n otel-demo  get pods | grep -Ev "Running|Completed" || echo "(全部就绪)"
kubectl -n chaos-mesh get pods | grep -Ev "Running|Completed" || echo "(全部就绪)"

# 3) 串行采集（关键纪律：串行 + 逐场景回传，不要等全部采完）
cd /root/sre-incident-agent && source .venv/bin/activate
nohup bash -c 'for f in scenarios/mvp/00*.yaml; do echo "=== $f ==="; make fault SCENARIO="$f"; done' > /root/collect.log 2>&1 &
```

```powershell
# 4) 本机逐场景取回（注意：不要用 scp -r 整个 snapshots/ 目录，会套成 snapshots\snapshots\）
foreach ($d in "checkout-pod_crash-seed42","product-catalog-high_latency-seed42","payment-http_abort-seed42") {
  scp -r "<ecs-host>:/root/sre-incident-agent/snapshots/$d" "<local-repo>\snapshots\" }
```

## 4. 情景 C：从零开始（新实例）

**核心纪律：镜像源配置必须早于首次 `make up`（顺序不可颠倒）。**

| # | 动作 | 判据 |
|---|---|---|
| 1 | scp [`deploys/scripts/cloud-bootstrap.sh`](scripts/cloud-bootstrap.sh) 到 `/root/`（安装 docker/kind/helm/kubectl + 镜像源） | 文件存在 |
| 2 | scp `.env` 到 `/root/sre-incident-agent/.env`（**KUBECONFIG 必须绝对路径**——`~` 不会被展开） | 3 个 URL 齐 |
| 3 | `sed -i 's/\r$//' /root/cloud-bootstrap.sh` 后：`MIRROR=https://docker.m.daocloud.io bash /root/cloud-bootstrap.sh` | 末尾汇总无 FAIL |
| 4 | scp `infra/certs.d`（**4 个** hosts.toml：docker.io/ghcr.io/quay.io/registry.k8s.io）+ `infra/kind-config.yaml` | 4 个目录 |
| 5 | scp 5 个 chart 包到 `/root/local-charts/` + [`deploys/scripts/setup-local-helm-repo.sh`](scripts/setup-local-helm-repo.sh)、[`deploys/scripts/kind-prepull.sh`](scripts/kind-prepull.sh) 到 `/root/` | chart 包：kube-prometheus-stack / loki / tempo / opentelemetry-demo / chaos-mesh |
| 6 | `bash /root/setup-local-helm-repo.sh` | `helm repo list` 的 4 个仓库 URL 全为 `http://127.0.0.1:8879` |
| 7 | `kind create cluster --name sre-incident-agent --config infra/kind-config.yaml --kubeconfig /root/.kube/config` | 6 步 ✓ |
| 8 | 校验节点内镜像源：`docker exec sre-incident-agent-control-plane sh -c 'ls /etc/containerd/certs.d/'` | 4 目录 + containerd 2.x |
| 9 | `make up 2>&1 \| tee /root/makeup.log` | 结尾 `Cluster ready` |
| 10 | 若第 9 步在 astronomy-shop 超时 → `bash /root/kind-prepull.sh` 后再重跑 `make up` | 汇总无失败 |
| 11 | `kubectl -n monitoring rollout restart daemonset/otel-collector` + `kubectl apply -f infra/expose-nodeports.yaml` | tempo/loki endpoints 非空 |
| 12 | `make health-check` | `Passed: 6  Failed: 0` |

## 5. 情景 B：只重建集群（实例在、集群没了）

```bash
bash /root/setup-local-helm-repo.sh                     # 1) chart 仓库先起来（helm 装 chart 依赖它）
cd /root/sre-incident-agent && kind create cluster --name sre-incident-agent \
  --config infra/kind-config.yaml --kubeconfig /root/.kube/config   # 2)
bash /root/kind-prepull.sh                              # 3) 宿主机预拉（避免 kubelet 串行拉取拖超时）
source .venv/bin/activate && make up 2>&1 | tee /root/makeup.log    # 4) 幂等
# 5) 收尾同 §4 第 11–12 步
```

## 6. 坑清单（症状 → 根因 → 处置，精简版）

| 症状 | 根因 | 处置 |
|---|---|---|
| `ghcr.io` 拉取 ~50 KB/s | 该镜像源链路异常（**国内源之间差 200×，不能外推**） | `certs.d/ghcr.io/hosts.toml` 指向 `ghcr.nju.edu.cn`（实测 10 MB/s） |
| `helm repo add` 报 `context deadline exceeded` | `*.github.io` 的大 index.yaml 正文拉不动 | 用本地 chart 仓库（`setup-local-helm-repo.sh`） |
| `helm repo add` 报 `could not find protocol handler for: file` | helm 不支持 `file://` 仓库 | 改 `python3 -m http.server --bind 127.0.0.1` 托管 |
| `helm install --wait` 超时 | kubelet **串行**拉取（大件堵队列，"等待 11 分钟"是排队不是带宽） | `kind-prepull.sh` 预拉 + kind load |
| `kind create` 说 `already exists` 但集群不存在 | 真实错误被 `2>/dev/null \|\| echo` 吞掉 | 手工复现原命令；**首次跑就说"已存在"= 一定失败** |
| `kubectl` 报 `context "kind-..." does not exist` | `.env` 里 `KUBECONFIG=~/.kube/config`，**波浪号不展开** | 改绝对路径 |
| `pip install` 报 `from versions: none` | setuptools 拉取失败（构建隔离子进程） | `export PIP_INDEX_URL=https://mirrors.cloud.aliyuncs.com/pypi/simple/`（环境变量保证继承） |
| tempo/loki 端口不通 | **chart 不支持 pin nodePort** | `kubectl apply -f infra/expose-nodeports.yaml`（alertmanager 的 kps 91.4.1 支持 values 定号，可写进 values） |
| collector 刷 `remotewrite deadline exceeded` | remote_write 指向不存在的服务名 | 改为 `prometheus-kube-prometheus-prometheus:9090` 后 rollout restart |
| 评测报 `snapshot_missing` | Windows 默认 cp936 读 UTF-8 YAML 失败被吞 | 跑前设置 `PYTHONUTF8=1` |
| `helm upgrade` 报 `has no deployed releases` | 上次 install 失败，release 停在 failed | `helm uninstall <release> -n <ns>` 后重跑 `make up` |
| 实例重启后调查/采集全断 | ① 本地 chart 仓库不自启 ② watchdog 为 nohup 进程 | 重启后按 §3 第 0 步恢复；watchdog 需手工拉起（`make watchdog`） |

> 本节 12 项为实测踩坑中**可复用**的关键项（含根因）。更细的排查方法（如 kind 配置字段层级、NodePort pin 不支持、remote_write 服务名的完整取证过程）属于部署当时的现场记录，未随仓库分发——本文件已覆盖可复用的结论部分。

## 7. 时间与成本预算（实测）

| 阶段 | 时长 | 说明 |
|---|---|---|
| 从零部署 | 60–90 分钟 | 含镜像源配置与预拉 |
| 重建集群 | ~25 分钟 | 实例与 chart 仓库就绪前提下 |
| 单场景采集 | ~7 分钟 | 注入 + 等待 + 快照 |
| 11 场景全量评测（3 轮） | ~15 分钟 / $0.06 | deepseek 实价口径 |
| 单次告警调查 | ~30 秒 / ~$0.003 | 告警→开查 2 秒，注入→报告 94 秒 |

## 8. 安全与清理

- **凭据**：`.env`（LLM Key）与企微 webhook URL 只留在服务器，**绝不入 git**（日志已做 host-only 脱敏）；仓库历史上的凭据泄漏检查为 0 命中
- **端口**：安全组**只开 22**（SSH）——观测组件全部经 localhost/SSH 隧道访问，无需入方向
- **释放**：证据取回后即可释放实例（按量计费停止）；释放前核对 `snapshots/`、`artifacts/`、报告与截图全部已 scp 回本地
