# Polymarket Editorial Telegram Bot

Bot posts exactly 4 thematic briefs per day (in Russian) and separate whale alerts.

## Daily structure (UTC)

- 08:00 — Politics
- 10:00 — Economy
- 12:00 — Sports
- 14:00 — Other

Each post contains:
- short Russian intro (Gemini rewrite, strict data-only prompt)
- top 3 markets for the topic
- biggest move in 24h
- most active market in 24h

## Whale alerts

Separate checks run every 30 minutes. If detected amount is above `$100,000`, the bot posts a standalone alert.

Important limitation: current Gamma flow used in this project does not expose a reliable per-trade stream here, so whale detection is implemented as a lightweight approximation from high market activity (`volume_24h >= 100000`). This is documented in code comments.

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
```
