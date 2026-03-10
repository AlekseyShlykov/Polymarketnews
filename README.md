# Polymarket Daily Digest Bot

Fetches Polymarket data, finds the biggest 24h probability moves, and sends a short digest to Telegram. No manual approval. Use locally or via GitHub Actions.

## What it does

1. Fetches active events/markets from the **Polymarket Gamma API** (no CLOB).
2. Uses Gamma’s `lastTradePrice` / `bestBid`/`bestAsk` and `oneDayPriceChange` for current price and 24h move.
3. Filters by liquidity and minimum move size, ranks by absolute move.
4. Builds a template-based digest and sends it via the **Telegram Bot API**.
5. If the API fails or no signals pass the threshold, sends a **fallback digest** and does not crash.

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
python main.py
```

Only two env vars are required:

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHAT_ID` | Chat or channel ID (e.g. @userinfobot) |

`.env` is loaded from the project root (directory containing `config.py`). Run from any folder; `python main.py` is enough.

## File structure

```
.
├── .env.example
├── .github/workflows/daily_digest.yml
├── config.py           # TELEGRAM_* from .env; other defaults in code
├── main.py             # Entrypoint: fetch → analyze → format → send
├── polymarket_client.py # Gamma API only, defensive parsing
├── analyzer.py         # Filter and rank by 24h move
├── formatter.py        # Template digest + fallback text
├── telegram_sender.py  # Telegram Bot API
├── utils.py            # Logging setup
├── requirements.txt
├── pytest.ini
├── README.md
└── tests/test_analyzer.py
```

## Fallback message

When no markets pass the thresholds (or the API fails), the bot still sends:

```
Polymarket Daily Digest — YYYY-MM-DD

No major probability moves passed the configured thresholds in the last 24 hours.
```

## GitHub Actions

1. Add repo secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
2. Workflow runs daily at 12:00 UTC; you can also trigger it manually (Actions → Daily digest → Run workflow).

## Tests

```bash
pytest -v
```

## MVP notes

- **Gamma only**: No CLOB; price and 24h change come from Gamma market fields.
- **Thresholds** are in `config.py` (e.g. `MIN_LIQUIDITY`, `MIN_ABS_DELTA_24H`). Change them there if you want different filters.
