#!/bin/bash
# 安装 a-trade scheduler 到 macOS launchd
# 自动开机启动，崩溃自动重启
set -e

PLIST_SRC="$(cd "$(dirname "$0")/.." && pwd)/launchd/com.a-trade.scheduler.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.a-trade.scheduler.plist"

echo "=== 安装 a-trade scheduler ==="
echo "源: $PLIST_SRC"
echo "目标: $PLIST_DST"

# 先停止旧的
launchctl unload "$PLIST_DST" 2>/dev/null || true

# 复制
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DST"

# 加载
launchctl load "$PLIST_DST"
echo "✅ 已加载"

# 启动
launchctl start com.a-trade.scheduler
echo "✅ 已启动"

echo ""
echo "=== 状态 ==="
launchctl list | grep a-trade || echo "未找到（可能需几秒）"

echo ""
echo "=== 日志 ==="
echo "tail -f /Users/jojo/code/a-trade/logs/scheduler.out.log"
echo "tail -f /Users/jojo/code/a-trade/logs/scheduler.err.log"

echo ""
echo "=== 卸载命令 ==="
echo "bash scripts/uninstall_launchd.sh"
