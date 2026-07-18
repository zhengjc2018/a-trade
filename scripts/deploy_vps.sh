#!/usr/bin/env bash
# a-trade VPS 快速部署脚本
#
# 适用环境：
# - Ubuntu / Debian 系 VPS
# - Python 3.10+（推荐 3.11/3.12）
#
# 用法：
#   bash scripts/deploy_vps.sh
#   bash scripts/deploy_vps.sh /opt/a-trade
#
# 说明：
# - 会创建虚拟环境
# - 安装运行依赖
# - 生成 .env（若不存在）
# - 可选创建 systemd 服务并启动

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${1:-$REPO_DIR}"
VENV_DIR="$APP_DIR/.venv"
SERVICE_NAME="a-trade"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

echo "=== a-trade VPS 快速部署 ==="
echo "项目目录: $APP_DIR"

if [[ ! -d "$APP_DIR" ]]; then
  echo "错误：目录不存在: $APP_DIR" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "错误：未找到 python3，请先安装 Python 3" >&2
  exit 1
fi

PY_VER="$(python3 - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
echo "Python: $PY_VER"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "创建虚拟环境: $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip wheel setuptools

if [[ -f "$APP_DIR/requirements.txt" ]]; then
  echo "安装依赖: requirements.txt"
  pip install -r "$APP_DIR/requirements.txt"
else
  echo "未找到 requirements.txt，按项目代码自动安装常见依赖"
  pip install \
    requests \
    pandas \
    numpy \
    loguru \
    python-dotenv \
    botpy \
    apscheduler \
    websockets
fi

if [[ ! -f "$APP_DIR/.env" ]]; then
  echo "生成 .env 模板"
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "请编辑 $APP_DIR/.env 填入真实配置后再启动。"
fi

mkdir -p "$APP_DIR/logs" "$APP_DIR/data/cache" "$APP_DIR/reports"

if [[ "${2:-}" == "--systemd" ]]; then
  if [[ $EUID -ne 0 ]]; then
    echo "systemd 安装需要 root 权限，请用 sudo 重新执行。" >&2
    exit 1
  fi

  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=a-trade scheduler
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$APP_DIR
ExecStart=$VENV_DIR/bin/python $APP_DIR/scripts/run_scheduler.py
Restart=always
RestartSec=10
StandardOutput=append:$APP_DIR/logs/scheduler.out.log
StandardError=append:$APP_DIR/logs/scheduler.err.log

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now "$SERVICE_NAME"
  systemctl status --no-pager "$SERVICE_NAME" || true
  echo "systemd 服务已安装并启动: $SERVICE_NAME"
  exit 0
fi

echo "运行自检: scripts/run_scheduler.py"
echo "提示：如果你还没填 .env，这一步会失败；先完善配置再启动。"
exec "$VENV_DIR/bin/python" "$APP_DIR/scripts/run_scheduler.py"
