#!/usr/bin/env bash
# =============================================================================
# kind-prepull.sh —— 方案 C：宿主机预拉 + kind load（make up 因 --wait 超时时的兜底）
# -----------------------------------------------------------------------------
# 原理：Pod 镜像由节点内 containerd 拉取，`helm install --wait` 的 timeout 会撞上
#       缓慢的 docker.io/ghcr 通路。本脚本改为：
#         宿主机 Docker（有 daemon.json 镜像加速器）预拉全部镜像 → kind load 导入节点
#       → Pod 无需联网拉镜像 → --wait 超时问题从根上消失。
#
# 用法（在 ECS 上，仓库根目录随意，脚本会用 REPO_DIR）：
#   bash /root/kind-prepull.sh
#
# 可选环境变量：
#   REPO_DIR   仓库路径（默认 /root/sre-incident-agent）
#   CLUSTER    kind 集群名（默认 sre-incident-agent）
#
# 幂等：已存在的镜像不会重复拉取。任何单个镜像失败都不中断，最后统一汇总。
# 关键前提：本文件必须是 LF 换行（从 Windows 传过去先 sed -i 's/\r$//'）。
# =============================================================================

set -uo pipefail

REPO_DIR="${REPO_DIR:-/root/sre-incident-agent}"
CLUSTER="${CLUSTER:-sre-incident-agent}"
MANIFEST=/root/images.txt        # 枚举出的完整镜像清单
OKLIST=/root/prepull-ok.txt      # 已就绪（本地已有 / 预拉成功）
FAILLIST=/root/prepull-fail.txt  # 三种源都失败的
COLLECT=/tmp/collect_images.py

cd "$REPO_DIR" 2>/dev/null || { echo "!! 找不到仓库目录 $REPO_DIR"; exit 1; }

PY="$REPO_DIR/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || echo python3)"

# -----------------------------------------------------------------------------
echo "==> 1/4 枚举镜像（helm template × 5 + collector DaemonSet）"
# -----------------------------------------------------------------------------
# 注意：python 读取的是【管道传入的 stdin】，所以代码本体必须先落成文件，
#       不能用 `python - <<'PY'`（那样 stdin 会变成 heredoc 而不是渲染结果）。
cat > "$COLLECT" <<'PY'
import sys
import yaml

found = []


def walk(node):
    """收集所有 image 字段：字符串形式，以及 {repository, tag} 字典形式。"""
    if isinstance(node, dict):
        for key, val in node.items():
            if key == "image":
                if isinstance(val, str) and val.strip():
                    found.append(val.strip())
                elif isinstance(val, dict):
                    repo = val.get("repository")
                    tag = val.get("tag") or val.get("digest")
                    if repo:
                        found.append(f"{repo}:{tag}" if tag else str(repo))
            else:
                walk(val)
    elif isinstance(node, list):
        for item in node:
            walk(item)


try:
    for doc in yaml.safe_load_all(sys.stdin):
        walk(doc)
except Exception as exc:          # noqa: BLE001 - 渲染结果里混入注释/非 YAML 时不应中断
    print(f"# yaml parse warning: {exc}", file=sys.stderr)

seen = set()
for image in found:
    if not image or "@" in image:   # 跳过 digest 引用
        continue
    if image not in seen:
        seen.add(image)
        print(image)
PY

{
  helm template prometheus     prometheus-community/kube-prometheus-stack -n monitoring \
       --values infra/helm/prometheus-values.yaml 2>/dev/null
  helm template tempo          grafana/tempo        -n monitoring --values infra/helm/tempo-values.yaml 2>/dev/null
  helm template loki           grafana/loki         -n monitoring --values infra/helm/loki-values.yaml  2>/dev/null
  helm template astronomy-shop open-telemetry/opentelemetry-demo -n otel-demo \
       --values infra/helm/astronomy-shop-values.yaml 2>/dev/null
  helm template chaos-mesh     chaos-mesh/chaos-mesh -n chaos-mesh \
       --set chaosDaemon.runtime=containerd \
       --set chaosDaemon.socketPath=/run/containerd/containerd.sock 2>/dev/null
  cat infra/collector/otelcol-daemonset.yaml 2>/dev/null
} | "$PY" "$COLLECT" | sort -u > "$MANIFEST"

TOTAL="$(wc -l < "$MANIFEST" | tr -d ' ')"
echo "    枚举到 $TOTAL 个镜像"
if [ "$TOTAL" -eq 0 ]; then
  echo "!! 一个镜像都没枚举到 —— 多半是 helm repo 还没加（先跑一次 make up 的前半段）"
  exit 1
fi
sed 's/^/      /' "$MANIFEST"

# -----------------------------------------------------------------------------
echo "==> 2/4 逐个预拉（自动做 registry 前缀替换，拉完 tag 回原名）"
# -----------------------------------------------------------------------------
: > "$OKLIST"; : > "$FAILLIST"

# 返回该 registry 的候选镜像源（空格分隔，按顺序尝试）。空 = 无镜像源可用。
mirrors_for() {
  case "$1" in
    ghcr.io/*)         echo "ghcr.nju.edu.cn ghcr.m.daocloud.io" ;;   # 实测首选南大
    quay.io/*)         echo "quay.m.daocloud.io quay.nju.edu.cn" ;;
    registry.k8s.io/*) echo "k8s.m.daocloud.io k8s.mirrors.nju.edu.cn" ;;
    gcr.io/*)          echo "gcr.m.daocloud.io gcr.nju.edu.cn" ;;
    *)                 echo "" ;;
  esac
}

N=0
while IFS= read -r IMG; do
  [ -z "$IMG" ] && continue
  N=$((N + 1))
  printf '  [%2d/%s] %s\n' "$N" "$TOTAL" "$IMG"

  if docker image inspect "$IMG" >/dev/null 2>&1; then
    echo "            = 本地已有，跳过"
    echo "$IMG" >> "$OKLIST"
    continue
  fi

  PULLED=""
  for M in $(mirrors_for "$IMG"); do
    SRC="${M}/${IMG#*/}"
    if docker pull "$SRC" >/dev/null 2>&1; then
      docker tag "$SRC" "$IMG" 2>/dev/null
      echo "            ✅ 经 $M"
      PULLED=yes; break
    else
      echo "            ✗ $M 失败"
    fi
  done

  # 无镜像源可映射的（docker.io / 裸名）：直接拉，宿主 registry-mirrors 自动生效
  if [ -z "$PULLED" ]; then
    if docker pull "$IMG" >/dev/null 2>&1; then
      echo "            ✅ 直连（走宿主 daemon.json 加速器）"
      PULLED=yes
    fi
  fi

  if [ -n "$PULLED" ]; then
    echo "$IMG" >> "$OKLIST"
  else
    echo "            ❌ 预拉失败"
    echo "$IMG" >> "$FAILLIST"
  fi
done < "$MANIFEST"

# -----------------------------------------------------------------------------
echo "==> 3/4 kind load（批量导入节点 $CLUSTER）"
# -----------------------------------------------------------------------------
if [ -s "$OKLIST" ]; then
  # shellcheck disable=SC2046
  kind load docker-image $(cat "$OKLIST") --name "$CLUSTER" 2>&1 | tail -25
else
  echo "    没有可导入的镜像，跳过"
fi

# -----------------------------------------------------------------------------
echo "==> 4/4 汇总"
# -----------------------------------------------------------------------------
OKC="$(wc -l < "$OKLIST" | tr -d ' ')"
echo "    预拉成功并已导入：$OKC / $TOTAL"
echo "    节点内镜像总数：$(docker exec "${CLUSTER}-control-plane" crictl images -q 2>/dev/null | wc -l)"

if [ -s "$FAILLIST" ]; then
  echo ""
  echo "  ⚠️ 以下镜像未能预拉（对应 Pod 仍会联网拉取，可能慢）："
  sed 's/^/      /' "$FAILLIST"
fi

cat <<'EOF'

  下一步：重新跑一次（幂等，已导入的镜像不会再拉）
      cd /root/sre-incident-agent && source .venv/bin/activate
      make up 2>&1 | tee /root/makeup.log

  验证：卡住的 Pod 事件应显示 "Container image ... already present on machine"
EOF
