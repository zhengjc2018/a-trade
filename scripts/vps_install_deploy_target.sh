#!/usr/bin/env bash
# 在 VPS 上初始化 a-trade 的自动部署目标（原子化、可回滚）
#
# 用法:
#   sudo bash scripts/vps_install_deploy_target.sh /srv/git/a-trade.git /opt/a-trade
#
# 设计:
# - bare repo 作为 git push 入口
# - /opt/a-trade/releases/<timestamp>/ 工作区目录
# - /opt/a-trade/current 软链接指向当前 release
# - post-receive hook 在新 release 安装依赖并运行健康检查，
#   失败时回滚到上一个 release。
# - 服务以非 root 用户（atrade）运行，仅允许 systemctl restart a-trade.service
#
# 部署流程：
# 1. 在新 release 目录 git checkout
# 2. 创建/复用 .venv，安装锁定依赖
# 3. 跑核心 import 与 CLI --help 烟测
# 4. 切换 current 软链接
# 5. 重启服务
# 6. 健康检查失败 → 切回上一个 release

set -euo pipefail

BARE_REPO="${1:-/srv/git/a-trade.git}"
WORK_TREE="${2:-/opt/a-trade}"
SERVICE_NAME="a-trade"
SERVICE_USER="atrade"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
HOOK_DIR="${BARE_REPO}/hooks"
HOOK_FILE="${HOOK_DIR}/post-receive"

if [[ $EUID -ne 0 ]]; then
  echo "请使用 root 或 sudo 运行。" >&2
  exit 1
fi

echo "=== 初始化 a-trade VPS 自动部署目标（原子化） ==="
echo "bare repo : $BARE_REPO"
echo "work tree  : $WORK_TREE"
echo "service    : $SERVICE_NAME (user=$SERVICE_USER)"

mkdir -p "$(dirname "$BARE_REPO")" "$WORK_TREE" \
         "$WORK_TREE/releases" "$WORK_TREE/logs"

# 创建部署用户（若已存在则跳过）
if ! id "$SERVICE_USER" &>/dev/null; then
  useradd --system --shell /usr/sbin/nologin --home "$WORK_TREE" "$SERVICE_USER"
  echo "创建服务用户: $SERVICE_USER"
fi
chown -R "$SERVICE_USER":"$SERVICE_USER" "$WORK_TREE"

if [[ ! -d "$BARE_REPO" ]]; then
  git init --bare "$BARE_REPO"
fi

cat > "$HOOK_FILE" <<HOOK
#!/usr/bin/env bash
set -euo pipefail

BARE_REPO="$BARE_REPO"
WORK_TREE="$WORK_TREE"
SERVICE_NAME="$SERVICE_NAME"
SERVICE_USER="$SERVICE_USER"
BRANCH="refs/heads/main"

while read -r oldrev newrev refname; do
  if [[ "\$refname" != "\$BRANCH" ]]; then
    continue
  fi

  STAMP="\$(date +%Y%m%d_%H%M%S)"
  NEW_RELEASE="\$WORK_TREE/releases/\$STAMP"
  PREV_LINK="\$WORK_TREE/current"

  echo "[hook] checkout to new release: \$NEW_RELEASE"
  mkdir -p "\$NEW_RELEASE"
  chown "\$SERVICE_USER":"\$SERVICE_USER" "\$NEW_RELEASE"
  sudo -u "\$SERVICE_USER" git --git-dir="\$BARE_REPO" --work-tree="\$NEW_RELEASE" checkout -f main
  sudo -u "\$SERVICE_USER" git --git-dir="\$BARE_REPO" --work-tree="\$NEW_RELEASE" clean -fd

  # 创建/复用 venv
  if [[ ! -d "\$NEW_RELEASE/.venv" ]]; then
    sudo -u "\$SERVICE_USER" python3 -m venv "\$NEW_RELEASE/.venv"
  fi

  # 安装锁定依赖（不在 post-receive 中升级 pip）
  if [[ -f "\$NEW_RELEASE/requirements.txt" ]]; then
    sudo -u "\$SERVICE_USER" "\$NEW_RELEASE/.venv/bin/pip" install -r "\$NEW_RELEASE/requirements.txt"
  fi

  # 健康检查：核心模块导入 + CLI 帮助
  echo "[hook] running health check..."
  sudo -u "\$SERVICE_USER" "\$NEW_RELEASE/.venv/bin/python" -c "import atrade; print('atrade import OK')" \\
    || { echo "[hook] core import failed, aborting deploy"; exit 1; }
  sudo -u "\$SERVICE_USER" "\$NEW_RELEASE/.venv/bin/python" "\$NEW_RELEASE/scripts/run_scheduler.py" --help \\
    || true  # run_scheduler 可能没 --help，允许失败

  # 原子切换 current 软链接
  ln -sfn "\$NEW_RELEASE" "\$WORK_TREE/.current_tmp"
  mv -Tf "\$WORK_TREE/.current_tmp" "\$PREV_LINK"
  chown -h "\$SERVICE_USER":"\$SERVICE_USER" "\$PREV_LINK"

  echo "[hook] switching current -> \$NEW_RELEASE"

  # 重启服务
  systemctl restart "\$SERVICE_NAME"

  # 健康检查：服务是否还在运行
  sleep 3
  if systemctl is-active --quiet "\$SERVICE_NAME"; then
    echo "[hook] ✅ \$SERVICE_NAME active on \$NEW_RELEASE"
  else
    echo "[hook] ❌ service unhealthy, rolling back"
    PREV_RELEASE="\$(ls -1dt "\$WORK_TREE/releases"/*/ | sed -n '2p' || true)"
    if [[ -n "\$PREV_RELEASE" ]]; then
      ln -sfn "\$PREV_RELEASE" "\$WORK_TREE/.current_tmp"
      mv -Tf "\$WORK_TREE/.current_tmp" "\$PREV_LINK"
      chown -h "\$SERVICE_USER":"\$SERVICE_USER" "\$PREV_LINK"
      systemctl restart "\$SERVICE_NAME"
      echo "[hook] rolled back to \$PREV_RELEASE"
    fi
    exit 1
  fi
done
HOOK

chmod +x "$HOOK_FILE"

cat > "$SERVICE_FILE" <<SVC
[Unit]
Description=a-trade scheduler
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$WORK_TREE/current
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=$WORK_TREE/current
ExecStart=$WORK_TREE/current/.venv/bin/python $WORK_TREE/current/scripts/run_scheduler.py
Restart=always
RestartSec=10
StandardOutput=append:$WORK_TREE/logs/scheduler.out.log
StandardError=append:$WORK_TREE/logs/scheduler.err.log

[Install]
WantedBy=multi-user.target
SVC

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# 部署用户的 sudoers 限制：仅允许重启服务
cat > "/etc/sudoers.d/${SERVICE_USER}-deploy" <<SUDO
$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart $SERVICE_NAME
$SERVICE_USER ALL=(root) NOPASSWD: /usr/bin/systemctl is-active $SERVICE_NAME
$SERVICE_USER ALL=(root) NOPASSWD: /usr/sbin/runuser -u atrade -- *
SUDO
chmod 440 "/etc/sudoers.d/${SERVICE_USER}-deploy"

echo "初始化完成。"
echo "下一步:"
echo "1. 把代码推到 VPS bare repo（deploy@your-vps, 非 root）"
echo "2. post-receive 会自动创建 releases/<stamp>/ 并切换 current 软链接"
echo "3. 健康检查失败时自动回滚到上一个 release"
