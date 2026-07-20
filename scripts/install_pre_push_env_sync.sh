#!/usr/bin/env bash
# 安装 Git pre-push hook，用于同步本地 .env 到 VPS
#
# 用法:
#   bash scripts/install_pre_push_env_sync.sh deploy@your-vps /opt/a-trade/.env
#
# 安装后:
# - 每次 git push 前都会先 scp .env 到 VPS
# - .env 仍然不会进入 Git 历史或远端仓库

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK_SOURCE="$REPO_DIR/scripts/pre_push_sync_env.sh"
HOOK_DEST="$REPO_DIR/.git/hooks/pre-push"
TARGET="${1:-}"
REMOTE_ENV_PATH="${2:-/opt/a-trade/.env}"
SSH_PORT="${DEPLOY_SSH_PORT:-22}"

if [[ -z "$TARGET" ]]; then
  echo "用法: bash scripts/install_pre_push_env_sync.sh deploy@your-vps /opt/a-trade/.env" >&2
  exit 1
fi

if [[ ! -f "$REPO_DIR/.env" ]]; then
  echo "未找到本地 .env，请先创建并填写配置。" >&2
  exit 1
fi

cat > "$HOOK_DEST" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export DEPLOY_SSH_TARGET="$TARGET"
export DEPLOY_ENV_PATH="$REMOTE_ENV_PATH"
export DEPLOY_SSH_PORT="$SSH_PORT"
exec "$HOOK_SOURCE" "\$@"
EOF

chmod +x "$HOOK_DEST"
echo "已安装 pre-push hook: $HOOK_DEST"
echo "目标: $TARGET"
echo "远端 .env: $REMOTE_ENV_PATH"
