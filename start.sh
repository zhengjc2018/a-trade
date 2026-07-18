#!/bin/bash
# a-trade 一键启动脚本（设置 PYTHONPATH + 转发到 python）
# 用法: ./start.sh test_openclaw
#       ./start.sh scripts/test_openclaw.py
#       ./start.sh -m atrade.xxx
set -e
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"
exec python3 "$@"
