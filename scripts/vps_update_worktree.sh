#!/usr/bin/env bash
# VPS 侧手动同步工作区并重启服务
#
# 用法:
#   sudo bash scripts/vps_update_worktree.sh /srv/git/a-trade.git /opt/a-trade
#
# 这个脚本与 post-receive hook 逻辑一致，方便手动排障。

set -euo pipefail

BARE_REPO="${1:-/srv/git/a-trade.git}"
WORK_TREE="${2:-/opt/a-trade}"
SERVICE_NAME="a-trade"

if [[ $EUID -ne 0 ]]; then
  echo "请使用 root 或 sudo 运行。" >&2
  exit 1
fi

git --git-dir="$BARE_REPO" --work-tree="$WORK_TREE" checkout -f main
git --git-dir="$BARE_REPO" --work-tree="$WORK_TREE" clean -fd
systemctl restart "$SERVICE_NAME"
systemctl status --no-pager "$SERVICE_NAME" || true
