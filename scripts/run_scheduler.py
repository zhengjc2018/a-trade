"""启动 a-trade 调度器。

启动后会保持运行：
- botpy WebSocket 长连接
- APScheduler 定时任务
- 4 个自动推送任务：
  - 08:00 早盘快讯
  - 12:30 午盘报告
  - 15:30 收盘日报
  - 17:00 持仓新闻汇总

用法：
    ./start.sh scripts/run_scheduler.py

停止：
    Ctrl+C
"""

from __future__ import annotations

import signal
import sys
import time

from dotenv import load_dotenv
from loguru import logger

load_dotenv()


def main() -> int:
    logger.info("=== a-trade 调度器启动 ===")

    try:
        from atrade.scheduler import DailyScheduler
    except ImportError as e:
        logger.error(f"导入失败: {e}")
        logger.error("请确保在 a-trade 根目录运行，并执行过 pip install")
        return 1

    try:
        sched = DailyScheduler()
    except ValueError as e:
        logger.error(f"配置错误: {e}")
        return 1

    # 信号处理：优雅退出
    def _shutdown(signum, frame):
        logger.info(f"收到信号 {signum}，正在关闭...")
        sched.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    sched.start()
    logger.info("✅ 调度器运行中，按 Ctrl+C 停止")

    # 阻塞主线程
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        _shutdown(signal.SIGINT, None)

    return 0


if __name__ == "__main__":
    sys.exit(main())
