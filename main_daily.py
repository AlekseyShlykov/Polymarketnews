"""
Daily digest mode: at 18:00 UTC, post top 6 signals from the day's accumulated hourly candidates.
Deduplicates by market, ranks by score, then clears daily pool for the next day.
"""
import logging
import sys
from pathlib import Path

if __name__ == "__main__":
    _root = Path(__file__).resolve().parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

import config
from formatter import format_daily_digest
from state import (
    clear_daily_signals_for_new_day,
    get_daily_signals_for_digest,
    get_top_moves_for_digest,
    load_daily_signals,
)
from telegram_sender import send_telegram
from utils import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    logger.info("Daily digest run (18:00 UTC)...")

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env")
        sys.exit(1)

    daily = load_daily_signals()
    top_moves = get_top_moves_for_digest(daily, max_items=getattr(config, "TOP_MOVES_DAILY_COUNT", 5))
    top_signals = get_daily_signals_for_digest(daily, max_items=config.MAX_ITEMS_DAILY_DIGEST)
    text = format_daily_digest(top_moves, top_signals)
    logger.info("Sending daily digest: %s top moves, %s signals", len(top_moves), len(top_signals))
    if not send_telegram(text):
        logger.error("Telegram send failed")
        sys.exit(1)
    clear_daily_signals_for_new_day()
    logger.info("Daily digest sent; pool cleared for next day.")


if __name__ == "__main__":
    main()
