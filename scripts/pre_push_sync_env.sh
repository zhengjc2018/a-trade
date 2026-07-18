#!/usr/bin/env bash
# Git pre-push hook: 同步本地 .env 到 VPS，但不进入 Git 仓库
#
# 环境变量:
#   DEPLOY_SSH_TARGET 例如: root@96.30.194.21
#   DEPLOY_ENV_PATH    例如: /opt/a-trade/.env
#   DEPLOY_SSH_PORT    可选，默认 22
#   DEPLOY_SERVICE_NAME 可选，默认 a-trade.service
#
# 说明:
# - 只有当本地 .env 存在时才会同步
# - 同步失败会阻止 push，避免代码和配置不同步

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_ENV="$ROOT_DIR/.env"
TARGET="${DEPLOY_SSH_TARGET:-}"
REMOTE_ENV_PATH="${DEPLOY_ENV_PATH:-/opt/a-trade/.env}"
SSH_PORT="${DEPLOY_SSH_PORT:-22}"
SERVICE_NAME="${DEPLOY_SERVICE_NAME:-a-trade.service}"

if [[ -z "$TARGET" ]]; then
  echo "[pre-push] DEPLOY_SSH_TARGET 未设置，跳过 .env 同步" >&2
  exit 0
fi

if [[ ! -f "$LOCAL_ENV" ]]; then
  echo "[pre-push] 未找到本地 .env，跳过同步" >&2
  exit 0
fi

echo "[pre-push] 同步 .env -> ${TARGET}:${REMOTE_ENV_PATH}"
ssh -p "$SSH_PORT" "$TARGET" "mkdir -p \"\$(dirname \"$REMOTE_ENV_PATH\")\""
scp -P "$SSH_PORT" "$LOCAL_ENV" "${TARGET}:${REMOTE_ENV_PATH}"
ssh -p "$SSH_PORT" "$TARGET" "chmod 600 \"$REMOTE_ENV_PATH\""
ssh -p "$SSH_PORT" "$TARGET" "systemctl restart \"$SERVICE_NAME\""
echo "[pre-push] .env 同步完成"
