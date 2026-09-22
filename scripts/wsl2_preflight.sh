#!/usr/bin/env bash
# WSL2 preflight: increase inotify limits required by kind/K8s.
# Must be applied inside the kind container (not just the host namespace),
# because kind containers have their own inotify namespace on WSL2.
set -euo pipefail

REQUIRED_INSTANCES=1024
REQUIRED_WATCHES=1048576
CLUSTER_NAME="${CLUSTER_NAME:-sre-incident-agent}"
CONTAINER="${CLUSTER_NAME}-control-plane"

# Apply on host (best-effort, may not propagate to kind container)
current=$(cat /proc/sys/fs/inotify/max_user_instances 2>/dev/null || echo 0)
if [ "$current" -lt "$REQUIRED_INSTANCES" ]; then
  echo "==> Fixing inotify limits on host (current: $current)"
  docker run --rm --privileged alpine sh -c \
    "sysctl -w fs.inotify.max_user_instances=${REQUIRED_INSTANCES} && \
     sysctl -w fs.inotify.max_user_watches=${REQUIRED_WATCHES}" 2>/dev/null || true
fi

# Apply inside the kind container (persistent via sysctl.d)
if docker inspect "$CONTAINER" &>/dev/null; then
  inside=$(docker exec "$CONTAINER" sysctl -n fs.inotify.max_user_instances 2>/dev/null || echo 0)
  if [ "$inside" -lt "$REQUIRED_INSTANCES" ]; then
    echo "==> Fixing inotify limits inside $CONTAINER (current: $inside)"
    docker exec "$CONTAINER" sh -c "
      echo 'fs.inotify.max_user_instances=${REQUIRED_INSTANCES}' > /etc/sysctl.d/99-inotify.conf
      echo 'fs.inotify.max_user_watches=${REQUIRED_WATCHES}' >> /etc/sysctl.d/99-inotify.conf
      sysctl --system 2>&1 | grep inotify || true
    "
    echo "==> inotify inside $CONTAINER: $(docker exec "$CONTAINER" sysctl -n fs.inotify.max_user_instances)"
  else
    echo "==> inotify limits OK inside $CONTAINER (max_user_instances=$inside)"
  fi
else
  echo "==> kind container $CONTAINER not found yet (will fix after cluster creation)"
fi
