#!/usr/bin/env bash
# 在 VPS 上安装 a-trade-web systemd 服务。
#
# 用法: bash scripts/install_web_service.sh
set -euo pipefail

SERVICE_FILE="/etc/systemd/system/a-trade-web.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/../deploy/a-trade-web.service"

if [[ ! -f "$SOURCE" ]]; then
  echo "错误：未找到 $SOURCE" >&2
  exit 1
fi

cp "$SOURCE" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable a-trade-web
systemctl restart a-trade-web
sleep 2
systemctl --no-pager status a-trade-web
echo "==="
echo "Web 服务已启动。健康检查："
curl -sS http://127.0.0.1:8765/api/health || echo "(curl 失败)"
