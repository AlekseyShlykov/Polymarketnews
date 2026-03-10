"""Load only required env vars from .env (project root)."""
import os
from pathlib import Path

# Load .env from project root (directory containing config.py)
_ROOT = Path(__file__).resolve().parent
_env_path = _ROOT / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass

# Required for sending digest
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Polymarket and thresholds (fixed defaults; no env vars needed for MVP)
POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"
MIN_LIQUIDITY = 500.0
MIN_ABS_DELTA_24H = 5.0
MAX_ITEMS_IN_DIGEST = 10
MAX_MARKETS_TO_SCAN = 150
REQUEST_TIMEOUT_SECONDS = 30
