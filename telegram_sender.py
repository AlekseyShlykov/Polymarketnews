"""Send digest to Telegram via Bot API."""
import logging
import sys

import requests

import config

logger = logging.getLogger(__name__)


def send_telegram(text: str) -> bool:
    """Send text to TELEGRAM_CHAT_ID using TELEGRAM_BOT_TOKEN. Return True on success."""
    token = config.TELEGRAM_BOT_TOKEN
    chat_id = config.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=config.REQUEST_TIMEOUT_SECONDS)
        body = r.json() if r.text else {}
        if not r.ok:
            logger.error("Telegram API error: %s %s", r.status_code, body)
            return False
        if not body.get("ok"):
            logger.error("Telegram returned ok=false: %s", body)
            return False
        return True
    except requests.RequestException as e:
        logger.exception("Telegram request failed: %s", e)
        return False
    except ValueError as e:
        logger.error("Invalid Telegram response: %s", e)
        return False
