#!/usr/bin/env bash
# =============================================================================
# sre-incident-agent 云端初始化脚本
# -----------------------------------------------------------------------------
# 目标环境：阿里云 ECS · Ubuntu 24.04 LTS x86_64 · Docker 已由「扩展程序」装好
# 用法：
#   sudo -i
#   bash cloud-bootstrap.sh                       # 用默认设置
#   MIRROR=https://xxxx.mirror.aliyuncs.com bash cloud-bootstrap.sh
#
# 可选环境变量：
#   MIRROR     阿里云 ACR 镜像加速器地址（不填则跳过加速器配置，会警告）
#   TOOLS      已提前 scp 上来的 kind/kubectl/helm 二进制目录（默认 /tmp/tools）
#   REPO_DIR   仓库落地目录（默认 /root/sre-incident-agent）
#   REPO_URL   仓库地址
#   PIP_INDEX  pip 镜像源（默认清华）
#
# 特性：可重复执行（幂等）。任何一步失败都不会中断，最后统一汇总。
#
# 注意：本文件必须是 LF 换行。若从 Windows 复制过去报 “\r: command not found”，
#       先执行： sed -i 's/\r$//' cloud-bootstrap.sh
# =============================================================================

set -uo pipefail          # 刻意不用 -e：要跑完全部检查再汇总

BLUE='\033[1;34m'; GREEN='\033[1;32m'; RED='\033[1;31m'
YEL='\033[1;33m';  NC='\033[0m'
PASS=0; FAIL=0; WARN=0
ok()   { echo -e "  ${GREEN}[PASS]${NC} $*"; PASS=$((PASS+1)); }
bad()  { echo -e "  ${RED}[FAIL]${NC} $*"; FAIL=$((FAIL+1)); }
warn() { echo -e "  ${YEL}[WARN]${NC} $*"; WARN=$((WARN+1)); }
step() { echo -e "\n${BLUE}==> $*${NC}"; }

MIRROR="${MIRROR:-}"
TOOLS="${TOOLS:-/tmp/tools}"
REPO_DIR="${REPO_DIR:-/root/sre-incident-agent}"
REPO_URL="${REPO_URL:-https://github.com/<your-github-account>/<your-repo>}"
PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"

# 探测系统架构后缀（本方案为 x86_64）
ARCH_RAW="$(uname -m)"
if [ "$ARCH_RAW" = "x86_64" ]; then ARCH="amd64"; else ARCH="arm64"; fi


# -----------------------------------------------------------------------------
step "1/8  前置检查"
# -----------------------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
  bad "请用 root 运行（sudo -i 后执行，或 sudo bash $0）"
  echo "       否则后续 apt / sysctl / 写 /usr/local/bin 都会失败。"
  exit 1
fi
ok "当前用户是 root"

if grep -qi ubuntu /etc/os-release 2>/dev/null; then
  . /etc/os-release
  ok "系统：$PRETTY_NAME"
  case "${VERSION_ID:-}" in
    24.04) ok "版本 24.04 —— 自带 Python $(python3 -V 2>&1 | awk '{print $2}')，符合项目 >=3.12" ;;
    *)     warn "版本 ${VERSION_ID:-未知}：本项目要求 Python >=3.12，请确认 python3 -V" ;;
  esac
else
  warn "非 Ubuntu 系统，脚本里的 apt 命令可能不适用"
fi

if [ "$ARCH_RAW" = "x86_64" ]; then
  ok "架构 x86_64（与 g7a 实例匹配）"
else
  warn "架构 $ARCH_RAW —— 镜像与二进制需按此架构选择，请确认与实例规格一致"
fi

if command -v docker >/dev/null 2>&1; then
  ok "Docker 已安装：$(docker --version)"
  if docker info >/dev/null 2>&1; then
    ok "Docker daemon 可正常访问"
  else
    warn "Docker 已装但 daemon 未运行 —— 第 2 步会尝试启动"
  fi
else
  warn "未检测到 Docker —— 第 2 步会自动安装（下单页没勾「扩展程序 → Docker 社区版」就属正常）"
fi


# -----------------------------------------------------------------------------
step "2/8  安装系统依赖"
# -----------------------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
if apt-get update -qq 2>&1 | tail -2; then
  ok "apt update 完成"
else
  warn "apt update 有报错，继续尝试安装"
fi

if apt-get install -y -qq make git curl ca-certificates python3-venv jq gnupg >/dev/null 2>&1; then
  ok "已安装 make / git / curl / ca-certificates / python3-venv / jq / gnupg"
else
  bad "系统依赖安装失败，请手工执行： apt update && apt install -y make git curl python3-venv jq gnupg"
fi

# --- Docker：kind 的硬依赖。下单页若没勾「扩展程序 → Docker 社区版」就在这里补装 ---
if ! command -v docker >/dev/null 2>&1; then
  echo "  … 未检测到 Docker，开始安装"
  echo "     注意：绝不能用 snap 版 docker（snap 的 confinement 会破坏 kind）"
  if apt-get install -y -qq docker.io >/dev/null 2>&1; then
    ok "已通过 Ubuntu 源安装 docker.io"
  else
    warn "docker.io 安装失败，改用 Docker 官方源（走阿里云镜像，速度快）"
    install -m 0755 -d /etc/apt/keyrings
    if curl -fsSL --max-time 60 https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg \
         | gpg --dearmor -o /etc/apt/keyrings/docker.gpg 2>/dev/null; then
      chmod a+r /etc/apt/keyrings/docker.gpg
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://mirrors.aliyun.com/docker-ce/linux/ubuntu $(. /etc/os-release && echo "${VERSION_CODENAME:-noble}") stable" \
        > /etc/apt/sources.list.d/docker.list
      apt-get update -qq
      if apt-get install -y -qq docker-ce docker-ce-cli containerd.io >/dev/null 2>&1; then
        ok "已通过 docker-ce（阿里云源）安装"
      else
        bad "Docker 安装失败，请手工处理后再重跑本脚本"
      fi
    else
      bad "拿不到 Docker 源 GPG key，Docker 未安装"
    fi
  fi
fi

if command -v docker >/dev/null 2>&1; then
  systemctl enable --now docker >/dev/null 2>&1
  sleep 2
  if docker info >/dev/null 2>&1; then
    ok "Docker daemon 运行中：$(docker --version)"
  else
    bad "Docker 已装但 daemon 起不来 —— 查 systemctl status docker"
  fi
fi


# -----------------------------------------------------------------------------
step "3/8  内核参数 fs.inotify.*（kind / K8s 必需）"
# -----------------------------------------------------------------------------
cat > /etc/sysctl.d/99-inotify.conf <<'EOF'
# sre-incident-agent: kind 与 K8s 需要较大的 inotify 配额
fs.inotify.max_user_instances = 1024
fs.inotify.max_user_watches   = 1048576
EOF
if sysctl --system >/dev/null 2>&1; then
  INST="$(sysctl -n fs.inotify.max_user_instances 2>/dev/null || echo 0)"
  WATCH="$(sysctl -n fs.inotify.max_user_watches 2>/dev/null || echo 0)"
  if [ "$INST" -ge 1024 ] && [ "$WATCH" -ge 1048576 ]; then
    ok "已生效：max_user_instances=$INST, max_user_watches=$WATCH"
  else
    warn "参数未达目标值（instances=$INST, watches=$WATCH）—— 项目 preflight 会再兜一次"
  fi
else
  warn "sysctl --system 报错，项目自带 preflight 脚本仍会尝试修正"
fi


# -----------------------------------------------------------------------------
step "4/8  Docker 镜像加速器（拉镜像成败的关键）"
# -----------------------------------------------------------------------------
if [ -z "$MIRROR" ]; then
  warn "未提供 MIRROR，跳过。强烈建议配置，否则拉 Docker Hub 镜像会非常慢。"
  echo "       获取方式：阿里云控制台 → 容器镜像服务 ACR → 镜像工具 → 镜像加速器"
  echo "       然后重跑： MIRROR=https://<你的ID>.mirror.aliyuncs.com bash $0"
else
  mkdir -p /etc/docker
  if [ -f /etc/docker/daemon.json ]; then
    cp -n /etc/docker/daemon.json /etc/docker/daemon.json.bak 2>/dev/null || true
  fi
  cat > /etc/docker/daemon.json <<EOF
{
  "registry-mirrors": ["${MIRROR}"]
}
EOF
  if systemctl daemon-reload && systemctl restart docker && sleep 3; then
    ok "已写入 /etc/docker/daemon.json 并重启 docker"
    if docker info 2>/dev/null | grep -A 3 -i "Registry Mirrors" | grep -q "$MIRROR"; then
      ok "加速器已生效"
    else
      warn "docker info 未显示加速器，请手工核对 daemon.json"
    fi
  else
    bad "docker 重启失败，请检查 systemctl status docker"
  fi
fi


# -----------------------------------------------------------------------------
step "5/8  安装 kind / kubectl / helm"
# -----------------------------------------------------------------------------
install_bin() {   # install_bin <名字> <目标路径> <下载URL>
  local name="$1" dest="$2" url="$3"
  if command -v "$name" >/dev/null 2>&1; then
    ok "$name 已在 PATH 中：$($name version 2>/dev/null | head -1 || echo present)"
    return 0
  fi
  if [ -f "${TOOLS}/${name}" ]; then
    install -m 0755 "${TOOLS}/${name}" "$dest" && ok "$name 已从 ${TOOLS} 装好（推荐路径）"
    return 0
  fi
  echo "  … ${TOOLS}/${name} 不存在，尝试联网下载"
  if curl -fsSL --max-time 120 -o "$dest" "$url"; then
    chmod +x "$dest" && ok "$name 联网下载成功"
  else
    bad "$name 安装失败（国内直连 GitHub 常失败）"
    echo "       办法：在本地（有代理）下载 linux-${ARCH} 版，scp 到 ${TOOLS}/${name} 再重跑本脚本"
    rm -f "$dest"
  fi
}

mkdir -p "$TOOLS" /usr/local/bin
install_bin kind   /usr/local/bin/kind   "https://kind.sigs.k8s.io/dl/latest/kind-linux-${ARCH}"
install_bin kubectl /usr/local/bin/kubectl \
  "https://dl.k8s.io/release/$(curl -fsSL --max-time 20 https://dl.k8s.io/release/stable.txt 2>/dev/null || echo v1.31.0)/bin/linux/${ARCH}/kubectl"

# --- helm 是 tar.gz 包，绝不能像 kind/kubectl 那样直接 -o 落盘 ---
# 若直接落盘，装出来的 /usr/local/bin/helm 其实是压缩包，执行时报：
#   /usr/local/bin/helm: 1: Syntax error: word unexpected (expecting ")")
# 而且 `command -v helm` 仍会命中 → 看起来"装好了"，直到 helm repo update 才炸。
install_helm() {
  local ver="${HELM_VER:-v3.16.2}"
  if command -v helm >/dev/null 2>&1 && helm version --short >/dev/null 2>&1; then
    ok "helm 已在 PATH 中且可执行：$(helm version --short 2>/dev/null)"
    return 0
  fi
  if [ -x "${TOOLS}/helm" ] && "${TOOLS}/helm" version --short >/dev/null 2>&1; then
    install -m 0755 "${TOOLS}/helm" /usr/local/bin/helm && ok "helm 已从 ${TOOLS} 装好（推荐路径）"
    return 0
  fi
  echo "  … ${TOOLS}/helm 不可用，下载 helm-${ver}-linux-${ARCH}.tar.gz 并解包安装"
  if curl -fsSL --max-time 180 -o /tmp/helm.tgz "https://get.helm.sh/helm-${ver}-linux-${ARCH}.tar.gz" \
     && tar -xzf /tmp/helm.tgz -C /tmp \
     && install -m 0755 "/tmp/linux-${ARCH}/helm" /usr/local/bin/helm \
     && helm version --short >/dev/null 2>&1; then
    ok "helm 安装成功：$(helm version --short)"
  else
    bad "helm 安装失败 —— 本地下载 helm-${ver}-linux-${ARCH}.tar.gz，解出 helm 后 scp 到 ${TOOLS}/helm 再重跑"
    rm -f /usr/local/bin/helm
  fi
}
install_helm

# --- 收尾校验：三个工具必须真能"跑起来" ---
# 「下载成功」≠「装对了」：只看 command -v 会把压缩包/HTML 错误页当成装好。
for B in kind kubectl helm; do
  if command -v "$B" >/dev/null 2>&1; then
    if "$B" version --client >/dev/null 2>&1 || "$B" version >/dev/null 2>&1; then
      ok "$B 可执行验证通过"
    else
      bad "$B 在 PATH 中但无法正常运行 —— 极可能装的是压缩包或下载到的是错误页；删掉 /usr/local/bin/$B 后重跑"
    fi
  else
    bad "$B 不在 PATH 中"
  fi
done


# -----------------------------------------------------------------------------
step "6/8  拉取代码 + 建 venv + 装依赖"
# -----------------------------------------------------------------------------
if [ -d "$REPO_DIR/.git" ]; then
  ok "仓库已存在：$REPO_DIR"
elif [ -d "$REPO_DIR" ]; then
  ok "目录已存在（非 git 仓库，可能是 scp 上来的）：$REPO_DIR"
else
  echo "  … 尝试 git clone"
  if git clone --depth 1 "$REPO_URL" "$REPO_DIR" 2>&1 | tail -3; then
    ok "已克隆到 $REPO_DIR"
  else
    bad "git clone 失败（国内直连 GitHub 常失败）"
    echo "       办法：本地打包后 scp 上去，排除 .venv / .git："
    echo "         tar --exclude=.venv --exclude=.git -czf repo.tgz -C <本地仓库父目录> <仓库名>"
    echo "         scp repo.tgz root@<公网IP>:/root/ && ssh root@<公网IP> 'tar -xzf /root/repo.tgz -C /root'"
  fi
fi

if [ -d "$REPO_DIR" ]; then
  cd "$REPO_DIR" || bad "无法进入 $REPO_DIR"

  if [ -f pyproject.toml ]; then
    ok "找到 pyproject.toml"
    REQ="$(grep -E '^requires-python' pyproject.toml || true)"
    [ -n "$REQ" ] && echo "       项目要求：$REQ"
  else
    bad "$REPO_DIR 里没有 pyproject.toml，仓库可能没拉全"
  fi

  if [ ! -d .venv ]; then
    if python3 -m venv .venv; then
      ok "已创建 venv：$REPO_DIR/.venv"
    else
      bad "venv 创建失败 —— 检查是否装了 python3-venv"
    fi
  else
    ok "venv 已存在，跳过创建"
  fi

  if [ -x .venv/bin/pip ]; then
    echo "  … pip install -e \".[dev]\"  （首次约 15 分钟，请耐心）"
    if .venv/bin/pip install -q --upgrade pip -i "$PIP_INDEX" >/dev/null 2>&1 &&
       .venv/bin/pip install -q -i "$PIP_INDEX" -e ".[dev]" 2>&1 | tail -5; then
      ok "项目依赖安装完成"
      .venv/bin/python -c "import langgraph, langchain_openai, pandas; print('       import 自检通过')" 2>/dev/null \
        && ok "关键依赖 import 正常" \
        || warn "关键依赖 import 异常，请手工核查"
    else
      bad "pip install 失败（注意：Ubuntu 24.04 有 PEP 668 限制，必须用 venv 而不是系统 pip）"
    fi
  fi
fi


# -----------------------------------------------------------------------------
step "7/8  .env 检查"
# -----------------------------------------------------------------------------
if [ -d "$REPO_DIR" ]; then
  ENVF="$REPO_DIR/.env"
  if [ -f "$ENVF" ]; then
    ok ".env 存在"
    echo "       —— 变量清单（值已打码）——"
    while IFS= read -r line; do
      case "$line" in
        \#*|'') continue ;;
      esac
      k="${line%%=*}"; v="${line#*=}"
      k="$(echo "$k" | tr -d '[:space:]')"
      [ -z "$k" ] && continue
      vlen=${#v}
      if [ "$vlen" -gt 12 ]; then
        echo "       ${k}=${v:0:6}…${v: -4}    (len=$vlen)"
      else
        echo "       ${k}=${v}"
      fi
    done < "$ENVF"
    grep -qE '^PROMETHEUS_URL=' "$ENVF" || warn ".env 缺 PROMETHEUS_URL（采集遥测必需）"
    grep -qE '^TEMPO_URL='     "$ENVF" || warn ".env 缺 TEMPO_URL（采集遥测必需）"
    grep -qE '^LOKI_URL='      "$ENVF" || warn ".env 缺 LOKI_URL（采集遥测必需）"
    if grep -qE '^NIM_API_KEY=' "$ENVF"; then
      ok "含 NIM_API_KEY（采集阶段其实不需要它，评测在本地跑）"
    else
      warn ".env 没有 NIM_API_KEY —— 若只做采集没问题；想跑 make demo/investigate 才需要"
    fi
  else
    bad "缺少 .env（仓库里不含它，被 .gitignore 排除了）"
    echo "       办法：本地执行 scp \"<本地仓库>/.env\" root@<公网IP>:$REPO_DIR/.env"
    echo "       采集阶段至少要有 PROMETHEUS_URL / TEMPO_URL / LOKI_URL 三个变量"
  fi
fi


# -----------------------------------------------------------------------------
step "8/8  连通性预检（30 秒内判断能不能顺利拉镜像）"
# -----------------------------------------------------------------------------
probe() {   # probe <名字> <URL> <期望说明>
  local name="$1" url="$2" note="$3" code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$url" 2>/dev/null || echo 000)"
  if [ "$code" = "000" ]; then
    bad "${name} 不可达（${url}）  ${note}"
  elif [ "$code" = "401" ] || [ "$code" = "200" ] || [ "$code" = "302" ]; then
    ok "${name} 可达（HTTP ${code}）"
  else
    warn "${name} 返回 HTTP ${code}（${url}）  ${note}"
  fi
}

probe "Docker Hub"          "https://registry-1.docker.io/v2/" "拉 prometheus/grafana/chaos-mesh 需要"
probe "ghcr.io"             "https://ghcr.io/v2/"              "拉 opentelemetry-demo 需要（加速器不管 ghcr，可能偏慢）"
probe "GitHub"              "https://github.com"               "克隆仓库需要"
probe "dl.k8s.io"           "https://dl.k8s.io/release/stable.txt" "下载 kubectl 需要"
probe "Helm 官方源"         "https://get.helm.sh"              "下载 helm 需要"
probe "Prometheus chart 源" "https://prometheus-community.github.io/helm-charts/index.yaml" "helm repo 需要"
probe "Chaos Mesh chart 源" "https://charts.chaos-mesh.org/index.yaml" "helm repo 需要"
probe "DashScope API"       "https://dashscope.aliyuncs.com/compatible-mode/v1/models" "本地评测用（云端非必需）"

echo "  … 实际拉一个最小镜像，验证 docker 通路"
if docker pull hello-world >/dev/null 2>&1; then
  ok "docker pull 通路正常"
else
  bad "docker pull 失败 —— 优先检查镜像加速器与 Docker Hub 连通性"
fi


# -----------------------------------------------------------------------------
step "汇总"
# -----------------------------------------------------------------------------
echo -e "  ${GREEN}PASS=$PASS${NC}   ${RED}FAIL=$FAIL${NC}   ${YEL}WARN=$WARN${NC}"
echo ""
if [ "$FAIL" -gt 0 ]; then
  echo -e "  ${RED}有 $FAIL 项失败，先把上面标 [FAIL] 的处理掉再继续。${NC}"
else
  echo -e "  ${GREEN}各项检查通过，可以进入部署。${NC}"
fi

cat <<EOF

  接下来（每次新开 shell 都要先激活 venv）：
    cd $REPO_DIR
    source .venv/bin/activate

    make setup          # preflight + 检查 kind/helm/kubectl
    make up             # 建集群 + 装全部组件（首次拉镜像约 20 分钟）

  然后务必先探活三个端口，再做故障注入：
    curl -s localhost:9090/-/healthy && echo PROM_OK
    curl -s localhost:3200/ready     && echo TEMPO_OK
    curl -s localhost:3100/ready     && echo LOKI_OK

  任一不通就先别往下做（参见需求说明文档 §9 的两处上游配置疑点）。

  采集节奏：每采完一个场景，立刻把 snapshots/<id>/ 拷回本地，别等 7 个采完。
    scp -r root@<公网IP>:$REPO_DIR/snapshots/ <your-local-repo>/snapshots/

  全部采完后：释放实例 → 等 24 小时 → 那 100 元预留金额解冻、可全额提现。

EOF
