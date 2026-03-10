# Polymarket 2-Mode Signal Bot

Autonomous Telegram bot with **hourly signals** and a **daily digest at 18:00 UTC**. No manual approval. Uses only `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`.

## Modes

1. **Hourly** – Every hour: scan markets, pick **at most 1** best signal by score. Post to Telegram **only if** at least one market passes thresholds. Otherwise do not post.
2. **Daily digest** – Every day at **18:00 UTC**: send one message with the **top 6** signals from the day (accumulated from hourly runs). Deduplicated by market, ranked by score.

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env
# Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env
python main_hourly.py   # hourly run
python main_daily.py    # daily digest (e.g. after 18:00 UTC)
```

## File structure

```
.
├── .env
├── .env.example
├── .github/workflows/daily_digest.yml   # Runs every hour; at 18:00 UTC also runs daily digest
├── config.py              # TELEGRAM_* + thresholds (hourly/daily)
├── state.json             # Persisted: posted cooldown, market_volumes (created by runs)
├── daily_signals.json     # Persisted: day's signals for digest (created/cleared by runs)
├── main_hourly.py         # Hourly entrypoint
├── main_daily.py          # Daily digest entrypoint (18:00 UTC)
├── main.py                # Legacy one-shot digest
├── polymarket_client.py   # Gamma API, 1h + 24h metrics
├── hourly_analyzer.py     # Score, thresholds, pick best 1 signal
├── analyzer.py            # Legacy 24h filter/rank
├── formatter.py           # Hourly post + daily digest templates
├── state.py               # state.json + daily_signals.json load/save, cooldown
├── telegram_sender.py
├── utils.py
├── requirements.txt
├── pytest.ini
├── README.md
└── tests/test_analyzer.py
```

## How hourly mode works

- **Schedule**: Runs once per hour (e.g. cron `0 * * * *`).
- **Data**: Fetches markets from Gamma (with `oneHourPriceChange`, `volume24hr`, liquidity, etc.). Uses **state** to get previous run’s `volume24hr` per market so it can compute `volume_change_1h` (current volume24hr − previous).
- **Eligibility**: A market is a candidate only if:
  - `liquidity >= 5000`
  - Not on **12h cooldown** (same market not posted in last 12 hours)
  - Passes at least one of:
    - **Combined**: `volume_change_1h >= 100` and `abs(probability_delta_1h) >= 20`
    - **Large probability move**: `abs(probability_delta_1h) >= 20`
    - **Volume spike**: `volume_change_1h >= 100` and `hourly_volume_usd >= 2000` (hourly_volume_usd = volume24hr/24)
    - **New hot market**: market age &lt; 24h and daily volume ≥ 10000
- **Scoring**:  
  `score = 50*combined + 2*|probability_delta_1h| + 0.8*volume_growth_% + 0.2*log(hourly_volume_usd+1) + 0.1*log(liquidity_usd+1)`  
  The **highest-scoring** candidate is chosen.
- **Post**: If there is a candidate, one Telegram post is sent (headline, question, odds move, volume move, liquidity, templated “why it matters”, optional link). That market is recorded in **state** (cooldown) and the signal is appended to **daily_signals.json** for the digest.
- **No post**: If no market passes, nothing is sent; state is still updated (e.g. `market_volumes`) for the next hour.

## How the 18:00 UTC digest works

- **Schedule**: The same workflow runs every hour; when the current UTC hour is **18**, it runs `main_daily.py` after `main_hourly.py`.
- **Input**: Reads **daily_signals.json** (signals added by hourly runs during the day).
- **Processing**: Deduplicates by `condition_id` (keeps the highest score per market), sorts by score descending, takes **top 6**.
- **Message**: One Telegram message: “Polymarket Daily Digest — YYYY-MM-DD — 18:00 UTC” and for each of the 6: question, odds change, volume change if present, and one templated “why it matters” line.
- **Reset**: After sending, **daily_signals.json** is cleared so the next day starts with an empty pool.

## How cooldown works

- **state.json** holds a `posted` list: `{ condition_id, posted_at_utc }` for each hourly post.
- Before picking a signal, every candidate is checked: if that `condition_id` appears in `posted` with `posted_at_utc` within the last **12 hours**, the market is skipped.
- After posting an hourly signal, that market is appended to `posted` and entries older than 12 hours are pruned. So the same market is not posted again within 12 hours.

## How no-signal hours are handled

- If **no** market passes the thresholds in a given hour, **nothing is posted**.
- The run still updates **state** (e.g. `market_volumes`) so the next hour can compute `volume_change_1h`.
- No error, no fallback message for that hour; the bot simply skips posting until the next run.

## State persistence (GitHub Actions)

- **state.json** and **daily_signals.json** live in the repo root. The workflow checks them out, runs `main_hourly.py` (and `main_daily.py` at 18:00 UTC), then **commits and pushes** any changes to these files so the next run sees updated state and daily pool.
- For local runs, the same files are read/written in the project directory.

## Workflow schedule

- **Single workflow** “Polymarket bot” runs at **minute 0 of every hour** (`0 * * * *`).
- Step 1: Run **main_hourly.py** (always).
- Step 2: If UTC hour is **18**, run **main_daily.py**.
- Step 3: Commit and push **state.json** and **daily_signals.json** if changed.

## Env vars

Only two are required (in `.env` or GitHub Secrets):

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHAT_ID`   | Chat or channel ID |

Thresholds and limits are in `config.py` (no extra env vars).

## Tests

```bash
pytest -v
```
