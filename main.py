"""
Daily digest: fetch → analyze → format → send.
Defensive: API failure or no signals → fallback digest, no crash.
"""
import logging
import sys
from pathlib import Path

# Ensure project root is on path when running as python main.py
if __name__ == "__main__":
    _root = Path(__file__).resolve().parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

import config
from analyzer import analyze_markets
from formatter import format_digest
from telegram_sender import send_telegram
from utils import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    logger.info("Starting Polymarket fetch...")

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env")
        sys.exit(1)

    try:
        logger.info("Analyzing probability moves...")
        items = analyze_markets()
    except Exception as e:
        logger.exception("Analysis failed: %s", e)
        items = []

    use_fallback = len(items) == 0
    if use_fallback:
        logger.info("No strong signals — using fallback digest")
    else:
        logger.info("Found %s signals", len(items))

    digest = format_digest(items, use_fallback=use_fallback)
    print(digest)

    logger.info("Sending Telegram message...")
    if not send_telegram(digest):
        logger.error("Telegram send failed")
        sys.exit(1)
    logger.info("Done. Telegram message sent.")


if __name__ == "__main__":
    main()
