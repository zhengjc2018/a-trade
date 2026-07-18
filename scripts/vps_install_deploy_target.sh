#!/usr/bin/env bash
# 在 VPS 上初始化 a-trade 的自动部署目标
#
# 用法:
#   sudo bash scripts/vps_install_deploy_target.sh /srv/git/a-trade.git /opt/a-trade
#
# 作用:
# - 创建 bare repo 作为 git push 入口
# - 创建工作区目录
# - 安装 post-receive hook
# - 创建/更新 systemd 服务
#
# 设计:
# - 本地只做 git push
# - VPS 收到 push 后自动更新工作区并重启服务

set -euo pipefail

BARE_REPO="${1:-/srv/git/a-trade.git}"
WORK_TREE="${2:-/opt/a-trade}"
SERVICE_NAME="a-trade"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
HOOK_DIR="${BARE_REPO}/hooks"
HOOK_FILE="${HOOK_DIR}/post-receive"

if [[ $EUID -ne 0 ]]; then
  echo "请使用 root 或 sudo 运行。" >&2
  exit 1
fi

echo "=== 初始化 a-trade VPS 自动部署目标 ==="
echo "bare repo : $BARE_REPO"
echo "work tree  : $WORK_TREE"

mkdir -p "$(dirname "$BARE_REPO")" "$WORK_TREE"

if [[ ! -d "$BARE_REPO" ]]; then
  git init --bare "$BARE_REPO"
fi

cat > "$HOOK_FILE" <<EOF
#!/usr/bin/env bash
set -euo pipefail

BARE_REPO="$BARE_REPO"
WORK_TREE="$WORK_TREE"
SERVICE_NAME="$SERVICE_NAME"
BRANCH="refs/heads/main"

while read -r oldrev newrev refname; do
  if [[ "\$refname" != "\$BRANCH" ]]; then
    continue
  fi

  echo "[hook] updating \$WORK_TREE from \$refname"
  git --git-dir="\$BARE_REPO" --work-tree="\$WORK_TREE" checkout -f main
  git --git-dir="\$BARE_REPO" --work-tree="\$WORK_TREE" clean -fd

  if [[ -x "\$WORK_TREE/.venv/bin/python" ]]; then
    "\$WORK_TREE/.venv/bin/python" -m pip install -U pip >/dev/null
  fi

  if [[ -f "\$WORK_TREE/requirements.txt" && -x "\$WORK_TREE/.venv/bin/pip" ]]; then
    "\$WORK_TREE/.venv/bin/pip" install -r "\$WORK_TREE/requirements.txt"
  fi

  systemctl restart "\$SERVICE_NAME"
  echo "[hook] restarted \$SERVICE_NAME"
done
EOF

chmod +x "$HOOK_FILE"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=a-trade scheduler
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$WORK_TREE
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$WORK_TREE
ExecStart=$WORK_TREE/.venv/bin/python $WORK_TREE/scripts/run_scheduler.py
Restart=always
RestartSec=10
StandardOutput=append:$WORK_TREE/logs/scheduler.out.log
StandardError=append:$WORK_TREE/logs/scheduler.err.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo "初始化完成。"
echo "下一步:"
echo "1. 把代码推到 VPS bare repo"
echo "2. 在 $WORK_TREE 里执行一次部署脚本创建虚拟环境"
echo "3. 启动服务: systemctl start $SERVICE_NAME"
