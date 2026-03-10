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
MIN_LIQUIDITY_HOURLY = 5000.0  # hourly mode: avoid low-quality
MIN_ABS_DELTA_24H = 5.0
MAX_ITEMS_IN_DIGEST = 10
MAX_ITEMS_DAILY_DIGEST = 6
MAX_MARKETS_TO_SCAN = 150
REQUEST_TIMEOUT_SECONDS = 30

# Hourly signal thresholds
HOURLY_COMBINED_VOLUME_CHANGE = 100.0
HOURLY_COMBINED_ABS_DELTA_PP = 20.0
HOURLY_LARGE_PROB_MIN_PP_24H = 10.0   # when only 24h data: treat as signal if |delta_24h| >= this
HOURLY_VOLUME_SPIKE_CHANGE = 100.0
HOURLY_VOLUME_SPIKE_MIN_USD = 2000.0
HOURLY_NEW_MARKET_AGE_HOURS = 24.0
HOURLY_NEW_MARKET_DAILY_VOLUME = 10000.0
