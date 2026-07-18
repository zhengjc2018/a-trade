#!/bin/bash
# 卸载 a-trade scheduler
set -e

PLIST_DST="$HOME/Library/LaunchAgents/com.a-trade.scheduler.plist"

echo "=== 卸载 a-trade scheduler ==="
launchctl unload "$PLIST_DST" 2>/dev/null || true
rm -f "$PLIST_DST"
echo "✅ 已卸载"
