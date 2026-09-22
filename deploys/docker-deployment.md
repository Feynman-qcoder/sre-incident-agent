# Docker 部署与镜像源配置（Docker Deployment）

> **本文的实测边界**（写清楚免得误读）：
> - ✅ **已实测**：镜像源速度与配置（`infra/certs.d/` 4 个 hosts.toml，2026-09 阿里云 ECS 实战）、kind 以 Docker 容器承载集群节点、节点内 containerd 配置校验命令。
> - ⚠️ **未在本机实测**：Windows / Docker Desktop 的安装步骤（依 Docker 官方文档编写；本项目的部署流程在 Linux Docker Engine 上实测通过）。

---

## 1. Docker 在本项目中的角色

本项目是 **Kubernetes 原生**的：故障注入依赖 **Chaos Mesh**（k8s operator）、根因取证要读 **K8s 事件**（`get_pod_events` 工具）、场景快照采集依赖 k8s 状态语义——因此部署载体是 **kind 集群**，而 kind 把集群节点跑在 **Docker 容器**里：

```bash
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
# sre-incident-agent-control-plane   kindest/node:v1.37.0   Up X hours
```

**为什么不提供 docker-compose 作为替代部署方式**：

compose 只能拉起「SUT + 观测后端」，**无法提供 Chaos Mesh 与 K8s 语义**——故障注入、带 ground truth 的快照采集、`get_pod_events` 工具会全部失效，评测链路也就无从谈起。所以 Docker 在本项目的**正确角色是 kind 的运行时**，而不是另一种部署形态。

> 只想看效果、不需要集群？不需要 Docker：`make demo-offline` + 双击 `webui/index.html`（见 [README](README.md) 三档门槛 ①）。

---

## 2. 安装与验证

### 2.1 Linux（Ubuntu / Alibaba Cloud Linux）

```bash
# 官方脚本（国内可加 --mirror Aliyun 走阿里云源）
curl -fsSL https://get.docker.com | bash -s docker --mirror Aliyun
systemctl enable --now docker

# 验证（就绪判据：能打印 Server 版本）
docker info --format '{{.OSType}} {{.ServerVersion}} {{.NCPU}}C/{{.MemTotal}}'
```

> 云端一键引导脚本（含 docker/kind/helm/kubectl 安装 + 镜像源）见 [`deploys/scripts/cloud-bootstrap.sh`](scripts/cloud-bootstrap.sh)，用法见 [aliyun-ecs-deployment.md](aliyun-ecs-deployment.md) §4。

### 2.2 Windows（必须走 WSL2）

1. 安装 **Docker Desktop**，安装时勾选 **Use WSL 2 based engine**；
2. 在 Docker Desktop → Settings → Resources → WSL Integration 中，**为你的发行版开启集成**；
3. **所有部署命令都在 WSL2 内执行**（`make` / `python3` / `kind` 均在 WSL2 中），不要在 PowerShell 里跑——`Makefile` 内部调用 `python3`，Windows 原生终端没有该命令。

```bash
# 在 WSL2 内验证
docker info --format '{{.OSType}} {{.ServerVersion}}'
```

> WSL2 的 inotify 限制会影响集群组件——仓库已备 `scripts/wsl2_preflight.sh`（`make setup` / `make up` 会自动调用；**重启 WSL 后需重跑**）。

---

## 3. 镜像源配置（国内网络必做，且顺序不可颠倒）

**核心纪律（实测教训）**：镜像源配置必须**早于首次 `make up`**。先拉起集群再配镜像源，等于让 kubelet 用慢速链路把镜像拉完一遍。

配置分**两层**，两层都要做：

### 3.1 宿主 Docker daemon（拉 kind 节点镜像 `kindest/node` 用）

编辑 `/etc/docker/daemon.json`：

```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.nju.edu.cn"
  ]
}
```

```bash
sudo systemctl restart docker
docker info | grep -A3 "Registry Mirrors"     # 确认已生效
```

### 3.2 kind 节点内 containerd（拉业务/观测组件镜像用）

仓库**已备好** `infra/certs.d/`（4 个 hosts.toml，与上表镜像源一致），并由 `infra/kind-config.yaml` 挂载进节点——无需手工编写：

| 域名 | 镜像源 | 说明 |
|---|---|---|
| `docker.io` | daocloud + nju | — |
| `ghcr.io` | **nju** | ⚠️ 实测 ghcr 走默认链路仅 **~50 KB/s**，改 nju 后 **~10 MB/s**（国内源之间差 **200×**，不能外推） |
| `quay.io` | daocloud + nju | — |
| `registry.k8s.io` | daocloud + nju | — |

对应的 kind 配置（`infra/kind-config.yaml`）关键两处：

```yaml
containerdConfigPatches:            # 集群级字段（写在 nodes: 之下会报字段不存在）
  - |-
    [plugins."io.containerd.grpc.v1.cri".registry]
      config_path = "/etc/containerd/certs.d"   # containerd 2.x（kind v0.27+）必须用 config_path 模式
nodes:
  - role: control-plane
    extraMounts:                    # 节点级字段
      - hostPath: ./infra/certs.d
        containerPath: /etc/containerd/certs.d
```

### 3.3 校验（节点内生效判据）

```bash
docker exec sre-incident-agent-control-plane sh -c 'ls /etc/containerd/certs.d/'
# 期望：docker.io  ghcr.io  quay.io  registry.k8s.io   （4 个目录）
```

---

## 4. 用 Docker 命令验证部署状态

```bash
# ① 集群节点（容器）在跑
docker ps --format '{{.Names}}\t{{.Status}}' | grep control-plane

# ② 节点内镜像源 4 个目录都在
docker exec sre-incident-agent-control-plane sh -c 'ls /etc/containerd/certs.d/ | wc -l'   # 期望 4

# ③ 容器资源占用（排查拉取/运行卡顿）
docker stats --no-stream sre-incident-agent-control-plane

# ④ 集群与后端健康（k8s 侧判据）
kubectl get nodes
make health-check        # 期望 Passed: 6  Failed: 0
```

> 实例/宿主重启后：集群容器通常会自启，但**本地 chart 仓库（`127.0.0.1:8879`）不会**——恢复步骤见 `aliyun-ecs-deployment.md` §3 第 0 步。

---

## 5. 常见问题（Docker 相关）

| 症状 | 根因 | 处置 |
|---|---|---|
| `docker info` 报 `Cannot connect to the Docker daemon` | daemon 未启动 / WSL2 未开集成 | `systemctl start docker`；Docker Desktop 中开启对应发行版的 WSL Integration |
| `kind create cluster` 卡在拉 `kindest/node` | 宿主 Docker 未配镜像源（§3.1） | 配 `daemon.json` 后重启 docker 再重试 |
| 业务镜像拉取极慢（`ghcr.io`） | 该源链路异常 | 确认 `infra/certs.d/ghcr.io/hosts.toml` 指向 `ghcr.nju.edu.cn`，并确认 `kind-config.yaml` 的 `extraMounts` 生效 |
| `helm install --wait` 超时 | kubelet **串行**拉取（排队而非带宽），大件堵队列 | `bash deploys/scripts/kind-prepull.sh` 预拉 + `kind load`；`make up` 幂等可重跑 |
| 端口 `9090/3200/3100` 不通 | chart 不支持 pin nodePort | `kubectl apply -f infra/expose-nodeports.yaml` |
| 磁盘吃紧 | 镜像 + 集群容器占空间 | `docker system df` 看占用；`kind delete cluster --name sre-incident-agent` 后 `docker system prune` |

> 更完整的坑清单（12 项，含根因）见 [aliyun-ecs-deployment.md](aliyun-ecs-deployment.md) §6——多数坑本地同样适用。

---

## 6. 说明：本仓库不含 Agent 的 Docker 镜像

本仓库**没有**提供 `Dockerfile` / 镜像化运行方式，原因有二：

1. **Agent 与评测都以本仓库为工作目录**（读 `snapshots/`、写 `artifacts/`、加载 `memory/`、调用 `webui/build_bundle.py`），`pip install -e .` + venv 是更直接的运行方式；
2. 本文件遵循一条纪律：**不写未经实测的部署方式**——若将来提供镜像，会先在真实环境构建并跑通 `make test` 与一次完整调查后再加入本文件。

如果你需要 Agent 容器化（例如 CI 内跑评测），可以提 Issue 说明场景，我再评估。
