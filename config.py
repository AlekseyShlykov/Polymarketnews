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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

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

# Editorial topic briefs
TOPIC_MIN_LIQUIDITY = 1000.0
TOPIC_MIN_VOLUME_24H = 3000.0
TOPIC_TOP_MARKETS = 4
TOPIC_MOVED_MAX = 1
# Max markets in today's top-N that may repeat yesterday's condition_ids (rest must be fresh).
TOPIC_DIGEST_MAX_REPEAT_PREVIOUS_DAY = 1

# Simple, robust importance score weights.
IMPORTANCE_W_VOLUME = 0.45
IMPORTANCE_W_LIQUIDITY = 0.25
IMPORTANCE_W_DELTA = 0.20
IMPORTANCE_W_RECENCY = 0.10

# Whale alerts (politics/economy use base threshold; sports/other need higher bar)
WHALE_BET_USD_THRESHOLD = 100000.0
WHALE_SPORTS_OTHER_USD_THRESHOLD = 300000.0
# Same market can alert again after this many hours (not a permanent block).
WHALE_ALERT_COOLDOWN_HOURS = 24.0
# Scan more markets for whales than for digests so hot politics/economy events are not missed.
WHALE_MAX_MARKETS_TO_SCAN = 400
WHALE_ALERTS_PATH = _ROOT / "whale_alerts.json"

# Multi-outcome event spotlight (Politics + Economy digests; min sibling markets)
POLITICS_SPOTLIGHT_MIN_MARKETS = 2
POLITICS_SPOTLIGHT_MAX_LINES = 8
# Looser than TOPIC_MIN_* so all siblings of a macro event can form a group (Gamma scan is capped).
SPOTLIGHT_MIN_LIQUIDITY = 500.0
SPOTLIGHT_MIN_VOLUME_24H = 800.0

# Economy digest: max crypto-related items in the top-4 (rest is macro/non-crypto economy)
ECONOMY_DIGEST_MAX_CRYPTO = 2

# Gemini
GEMINI_MODEL = "gemini-2.5-flash-lite"
GEMINI_TIMEOUT_SECONDS = 20
