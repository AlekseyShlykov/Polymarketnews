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

# Required for sending
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Polymarket
POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com"
MAX_MARKETS_TO_SCAN = 150
REQUEST_TIMEOUT_SECONDS = 30

# Hourly: min liquidity to consider a market (avoid noisy low-quality)
MIN_LIQUIDITY_HOURLY = 1000.0

# Editorial signal thresholds
# 1) Market shock: very sharp repricing in short period
MARKET_SHOCK_MIN_DELTA_3H_PP = 15.0   # abs(delta_3h) >= 15 (approximated from 24h)
MARKET_SHOCK_MIN_DELTA_6H_PP = 20.0  # OR abs(delta_6h) >= 20
# 2) Market trend: slower meaningful move over 24h (and NOT shock)
MARKET_TREND_MIN_DELTA_24H_PP = 10.0
# 3) Market disagreement: heavy trading, little price move
MARKET_DISAGREEMENT_VOL_CHANGE_6H_PCT = 70.0
MARKET_DISAGREEMENT_MAX_ABS_DELTA_6H_PP = 3.0
MARKET_DISAGREEMENT_MIN_DAILY_VOLUME = 10000.0
# 4) Activity spike (existing)
ACTIVITY_SPIKE_MIN_VOLUME_CHANGE_6H_PCT = 70.0
ACTIVITY_SPIKE_MIN_DAILY_VOLUME = 5000.0
# 5) Repricing (legacy; superseded by shock/trend where applicable)
REPRICING_MIN_DELTA_6H_PP = 10.0
REPRICING_MIN_DELTA_24H_PP = 15.0

# Daily digest
MAX_ITEMS_DAILY_DIGEST = 6
TOP_MOVES_DAILY_COUNT = 5

# Legacy (main.py / analyzer)
MIN_LIQUIDITY = 500.0
MIN_ABS_DELTA_24H = 5.0
MAX_ITEMS_IN_DIGEST = 10
