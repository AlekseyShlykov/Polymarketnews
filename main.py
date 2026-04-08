"""
Editorial mode entrypoint.
Modes:
- BOT_MODE=topic with TOPIC in {politics,economy,sports,other}
- BOT_MODE=whale for large-bet alerts
"""
import logging
import sys
import os
from pathlib import Path

# Ensure project root is on path when running as python main.py
if __name__ == "__main__":
    _root = Path(__file__).resolve().parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

import config
from analyzer import build_topic_brief_data, detect_whale_alerts, mark_whale_alert_sent
from formatter import format_topic_brief, format_whale_alert
from state import record_topic_digest_rotation
from telegram_sender import send_telegram
from utils import setup_logging

logger = logging.getLogger(__name__)


def main() -> None:
    setup_logging()
    logger.info("Starting editorial bot run...")

    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env")
        sys.exit(1)

    mode = (os.environ.get("BOT_MODE") or "topic").strip().lower()
    topic = (os.environ.get("TOPIC") or "other").strip().lower()
    data_window_hours_raw = (os.environ.get("DATA_WINDOW_HOURS") or "").strip()
    data_window_hours = None
    if data_window_hours_raw:
        try:
            data_window_hours = float(data_window_hours_raw)
        except ValueError:
            logger.warning("Invalid DATA_WINDOW_HOURS=%s, using default 24h mode.", data_window_hours_raw)

    if mode == "whale":
        alerts = detect_whale_alerts()
        if not alerts:
            logger.info("No new whale alerts.")
            return
        sent_count = 0
        for alert in alerts:
            text = format_whale_alert(alert)
            if send_telegram(text):
                mark_whale_alert_sent(alert)
                sent_count += 1
        if sent_count == 0:
            logger.error("No whale alerts were delivered.")
            sys.exit(1)
        logger.info("Sent %s whale alerts.", sent_count)
        return

    if topic not in {"politics", "economy", "sports", "other"}:
        logger.error("Invalid TOPIC: %s", topic)
        sys.exit(1)

    try:
        data = build_topic_brief_data(topic, window_hours=data_window_hours)
        text = format_topic_brief(data)
    except Exception as exc:
        logger.exception("Topic build failed: %s", exc)
        sys.exit(1)

    if not send_telegram(text):
        logger.error("Telegram send failed")
        sys.exit(1)
    if data.get("record_rotation"):
        ids = [
            str(m.get("condition_id") or "")
            for m in (data.get("top_markets") or [])
            if m.get("condition_id")
        ]
        record_topic_digest_rotation(topic, ids)
    logger.info("Topic brief sent for %s.", topic)


if __name__ == "__main__":
    main()
