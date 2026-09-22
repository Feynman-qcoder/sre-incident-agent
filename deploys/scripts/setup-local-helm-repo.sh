#!/usr/bin/env bash
# =============================================================================
# setup-local-helm-repo.sh —— 用本地 chart 包 + 本地 HTTP 服务替代 github.io 仓库
# -----------------------------------------------------------------------------
# 为什么需要（2026-09-16 实测）：
#   这台 ECS 上 `*.github.io` 的**小文件能拉、大文件正文拉不动**：
#     * chaos-mesh / open-telemetry 的 index.yaml 只有几十~几百 KB → `helm repo add` ✅
#     * prometheus-community / grafana 的 index.yaml 有 几 MB~十几 MB
#       → helm 报 `context deadline exceeded while reading body`（HEAD 200，正文超时）
#   注意：`curl -sI` 只发 HEAD —— **HEAD 200 完全不代表正文拉得动**。
#
# ⚠️ 版本更正：`helm repo add` **不支持 `file://` 协议**
#   （实测报 `Error: could not find protocol handler for: file`）。
#   因此这里改用**本地回环 HTTP 服务**托管 chart 目录：
#     `python3 -m http.server <PORT> --bind 127.0.0.1 --directory <CHARTS_DIR>`
#   只监听 127.0.0.1 → 不对外暴露，**不需要动安全组**。
#
# **仓库名保持与 Makefile 一致**（prometheus-community / grafana），
# 因此 Makefile 里 `helm upgrade --install <release> <repo>/<chart>` 一行都不用改。
#
# 前置：/root/local-charts/ 下已放入 *.tgz（本机经代理下载后 scp 上来）
# 用法：bash /root/setup-local-helm-repo.sh
# 可覆盖：CHARTS_DIR（默认 /root/local-charts）、PORT（默认 8879）
#
# 注意：实例重启或 `make down` 之后，本地 HTTP 服务不会自动拉起 →
#       重新跑一次本脚本即可（幂等）。
# =============================================================================

set -uo pipefail

CHARTS_DIR="${CHARTS_DIR:-/root/local-charts}"
PORT="${PORT:-8879}"
BASE="http://127.0.0.1:${PORT}"
HTTP_LOG=/root/local-repo-http.log
# 这四个名字必须与 Makefile 中 `<repo>/<chart>` 的写法一致。
# 全部指向本地服务 → 整套部署的 chart 下载彻底不碰外网
# （open-telemetry 的 chart 包从 github.com releases 下载会 `unexpected EOF`，
#   chaos-mesh 的 chart 在自家域名上，同样有正文被掐断的风险）
LOCAL_REPOS="prometheus-community grafana open-telemetry chaos-mesh"

# -----------------------------------------------------------------------------
echo "==> 1/4 检查 chart 包"
# -----------------------------------------------------------------------------
shopt -s nullglob
TGZ=("$CHARTS_DIR"/*.tgz)
if [ "${#TGZ[@]}" -eq 0 ]; then
  echo "!! $CHARTS_DIR 下没有 .tgz —— 先从本机 scp 上来："
  echo "     scp \"<本地图表包目录>/.tgz 三个包\" <ssh别名>:$CHARTS_DIR/"
  exit 1
fi
for f in "${TGZ[@]}"; do
  printf '    %-45s %8s\n' "$(basename "$f")" "$(du -h "$f" | cut -f1)"
done

# -----------------------------------------------------------------------------
echo "==> 2/4 生成仓库索引（URL 必须用 http://127.0.0.1:$PORT，**不能用 file://**）"
# -----------------------------------------------------------------------------
if ! helm repo index "$CHARTS_DIR" --url "$BASE"; then
  echo "!! helm repo index 失败"
  exit 1
fi
echo "    index.yaml 里 chart 的下载 URL 前两行（确认为 http://127.0.0.1）："
grep -m2 'http://127.0.0.1' "$CHARTS_DIR/index.yaml" | sed 's/^/      /' || true
echo "    收录的 chart："
sed -n 's/^  \([A-Za-z0-9._-]\{1,\}\):$/\1/p' "$CHARTS_DIR/index.yaml" | sort -u | sed 's/^/      /'

# -----------------------------------------------------------------------------
echo "==> 3/4 确保本地 chart HTTP 服务在运行（仅 127.0.0.1）"
# -----------------------------------------------------------------------------
probe_http() {
  curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$BASE/index.yaml" 2>/dev/null || echo 000
}
if [ "$(probe_http)" != "200" ]; then
  echo "    未在监听，启动 python3 -m http.server $PORT --bind 127.0.0.1"
  nohup python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$CHARTS_DIR" \
      > "$HTTP_LOG" 2>&1 &
  sleep 2
fi
CODE="$(probe_http)"
echo "    $BASE/index.yaml -> HTTP $CODE"
if [ "$CODE" != "200" ]; then
  echo "!! 本地 HTTP 服务没起来，看 $HTTP_LOG"
  exit 1
fi

# -----------------------------------------------------------------------------
echo "==> 4/4 注册仓库（名字与 Makefile 一致；--force-update 覆盖同名旧条目）"
# -----------------------------------------------------------------------------
for r in $LOCAL_REPOS; do
  helm repo add "$r" "$BASE" --force-update
done

echo
helm repo list
echo
echo "==> 验证索引里能查到这些 chart："
helm search repo kube-prometheus-stack --versions 2>/dev/null | head -3
helm search repo grafana/tempo      --versions 2>/dev/null | head -3
helm search repo grafana/loki       --versions 2>/dev/null | head -3
helm search repo open-telemetry/opentelemetry-demo --versions 2>/dev/null | head -3
helm search repo chaos-mesh/chaos-mesh             --versions 2>/dev/null | head -3

cat <<'EOF'

  下一步（幂等：kind 跳过已建集群、helm 用 upgrade --install、镜像已缓存的不会重下）：
      cd /root/sre-incident-agent && source .venv/bin/activate
      make up 2>&1 | tee /root/makeup.log

  两点说明：
  1) Makefile 里那两条指向 github.io 的 `helm repo add ... 2>/dev/null || true`
     仍会静默失败（仓库名已存在 → 报错被 || true 吞掉），但**不会覆盖**本仓库条目。
  2) `helm repo update` 会对全部 4 个仓库取索引：两个真实仓库（chaos-mesh /
     open-telemetry）本来就通，两个本地仓库走 127.0.0.1，因此这次应能完整跑过。
EOF
