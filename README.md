# Polymarket Editorial Telegram Bot

Bot posts exactly 4 thematic briefs per day (in Russian) and separate whale alerts.

## Daily structure (UTC)

- 08:00 — Politics
- 10:00 — Economy
- 12:00 — Sports
- 14:00 — Other

Each post contains:
- short Russian intro (Gemini rewrite, strict data-only prompt)
- top **4** markets for the topic (vs yesterday’s digest: at most 2 repeats, at least 2 new `condition_id`s when the pool allows)
- **Politics only:** extra block “Один сценарий — разные сроки” — one multi-outcome event with the highest total liquidity across its markets, with probability per deadline variant
- biggest move in 24h
- most active market in 24h

Digest rotation is stored in `digest_rotation.json` (committed by Actions when it changes).

## Whale alerts   

Separate checks run every 20 minutes. Detection uses the increase in `volume_24h` between snapshots (approximation, not individual trades).

- **Politics & Economy:** alert if interval volume increase ≥ **$100,000**
- **Sports:** only if increase ≥ **$300,000**
- **Other:** no whale posts

Important limitation: current Gamma flow used in this project does not expose a reliable per-trade stream here, so whale detection is implemented as a lightweight approximation from `volume_24h` increase between two 20-minute checks.

## Env vars / GitHub Secrets

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `GEMINI_API_KEY`

If Gemini fails or rate-limits, the bot falls back to deterministic Russian template text and still sends posts.

## Run locally

```bash
pip install -r requirements.txt
python main.py  # TOPIC/BOT_MODE can be set via env
```

Examples:

```bash
BOT_MODE=topic TOPIC=politics python main.py
BOT_MODE=whale python main.py
BOT_MODE=topic TOPIC=politics DATA_WINDOW_HOURS=2 python main.py
```

Scheduled runs only post one thematic brief per cron slot (no automatic posts on git push). For a local short-window test:

```bash
BOT_MODE=topic TOPIC=politics DATA_WINDOW_HOURS=2 python main.py
```

(`DATA_WINDOW_HOURS` disables yesterday-based rotation and the politics multi-outcome block uses the same fetch rules as production.)
