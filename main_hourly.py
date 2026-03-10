"""
Hourly mode: scan markets, pick best 1 signal, post only if one passes thresholds.
Updates state (cooldown, market_volumes) and appends to daily_signals for 18:00 digest.
"""
import logging
import sys
from pathlib import Path

if __name__ == "__main__":
    _root = Path(__file__).resolve().parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

import config
from formatter import format_hourly_post
from hourly_analyzer import pick_best_hourly_signal
from state import (
    add_daily_signal,
    load_daily_signals,
    load_state,
    record_posted,
    save_daily_signals,
    save_state,
    update_market_volumes,
)
from telegram_sender import send_telegram
from utils import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    logger.info("Hourly run: scanning for best signal...")

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env")
        sys.exit(1)

    try:
        best, state = pick_best_hourly_signal()
    except Exception as e:
        logger.exception("Hourly analysis failed: %s", e)
        try:
            st = load_state()
            st = update_market_volumes(st, {})
            save_state(st)
        except Exception:
            pass
        sys.exit(1)

    state = dict(state) if state else {}
    if best:
        text = format_hourly_post(best)
        logger.info("Posting 1 hourly signal: %s", (best.get("question") or "")[:50])
        if not send_telegram(text):
            logger.error("Telegram send failed")
            sys.exit(1)
        state = record_posted(best["condition_id"], state)
        daily = load_daily_signals()
        daily = add_daily_signal(best, daily)
        save_daily_signals(daily)
        logger.info("Signal posted and added to daily digest pool.")
    else:
        logger.info("No signal passed thresholds; skipping post.")

    save_state(state)
    logger.info("Hourly run done.")


if __name__ == "__main__":
    main()
