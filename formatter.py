"""
Format analyzer output as short news-style Telegram posts.
Never post empty or "nothing happened" messages — no-signal case is handled by not sending.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from gemini_client import build_topic_intro_with_gemini


def format_number(val: float | None) -> str:
    """Display number; avoid long decimals."""
    if val is None:
        return "—"
    try:
        v = float(val)
        if v == int(v):
            return str(int(v))
        return f"{v:.1f}"
    except (TypeError, ValueError):
        return "—"


def _market_url(slug: str) -> str:
    return f"https://polymarket.com/event/{slug}" if (slug or "").strip() else ""


def _clean_text(val: str | None) -> str:
    """
    Normalize question text for Telegram:
    - remove line breaks/tabs
    - collapse repeated whitespace
    - strip zero-width/BOM chars that can break rendering
    """
    if not val:
        return "Unknown"
    txt = str(val).replace("\u200b", "").replace("\ufeff", "")
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt or "Unknown"


def format_hourly_market_shock(signal: dict) -> str:
    """Market shock — very sharp repricing in short period."""
    q = _clean_text(signal.get("question"))
    old_p = format_number(signal.get("previous_probability"))
    new_p = format_number(signal.get("current_probability"))
    delta_6h = signal.get("delta_6h")
    delta_3h = signal.get("delta_3h")
    delta = delta_6h if delta_6h is not None else delta_3h
    if delta is None:
        delta = signal.get("delta_24h")
    delta_str = f" ({delta:+.1f} pp)" if delta is not None else ""
    liq = format_number(signal.get("liquidity"))
    vol = format_number(signal.get("volume_24h"))
    link = _market_url(signal.get("slug") or "")
    lines = [
        "🚨 Market shock",
        "",
        q,
        "",
        f"Odds moved: {old_p}% → {new_p}%{delta_str}",
        "",
        "A rapid repricing suggests traders are reacting strongly to new information.",
        "",
        f"Liquidity: ${liq}",
        f"24h volume: ${vol}",
    ]
    if link:
        lines.append("")
        lines.append(link)
    return "\n".join(lines).strip()


def format_hourly_market_trend(signal: dict) -> str:
    """Market trend — steady move over 24h."""
    q = _clean_text(signal.get("question"))
    old_p = format_number(signal.get("previous_probability"))
    new_p = format_number(signal.get("current_probability"))
    delta = signal.get("delta_24h")
    delta_str = f" ({delta:+.1f} pp) over 24h" if delta is not None else " over 24h"
    liq = format_number(signal.get("liquidity"))
    vol = format_number(signal.get("volume_24h"))
    link = _market_url(signal.get("slug") or "")
    lines = [
        "📈 Market trend",
        "",
        q,
        "",
        f"Odds moved: {old_p}% → {new_p}%{delta_str}",
        "",
        "The market has been steadily repricing expectations over the last day.",
        "",
        f"Liquidity: ${liq}",
        f"24h volume: ${vol}",
    ]
    if link:
        lines.append("")
        lines.append(link)
    return "\n".join(lines).strip()


def format_hourly_market_disagreement(signal: dict) -> str:
    """Market disagreement — heavy trading, little price move."""
    q = _clean_text(signal.get("question"))
    old_p = format_number(signal.get("previous_probability"))
    new_p = format_number(signal.get("current_probability"))
    delta_6h = signal.get("delta_6h")
    delta_str = f" ({delta_6h:+.1f} pp)" if delta_6h is not None else ""
    vol = format_number(signal.get("volume_24h"))
    link = _market_url(signal.get("slug") or "")
    lines = [
        "⚖️ Market disagreement",
        "",
        q,
        "",
        f"24h volume: ${vol}",
        "",
        f"Despite strong trading activity, odds barely moved: {old_p}% → {new_p}%{delta_str}",
        "",
        "This suggests the market is active but divided.",
    ]
    if link:
        lines.append("")
        lines.append(link)
    return "\n".join(lines).strip()


def format_hourly_repricing(signal: dict) -> str:
    """News-style: market repricing — odds moved sharply."""
    q = _clean_text(signal.get("question"))
    old_p = format_number(signal.get("previous_probability"))
    new_p = format_number(signal.get("current_probability"))
    delta_6h = signal.get("delta_6h")
    delta_24h = signal.get("delta_24h")
    delta = delta_6h if delta_6h is not None else delta_24h
    delta_str = f" ({delta:+.1f} pp)" if delta is not None else ""
    liq = format_number(signal.get("liquidity"))
    link = _market_url(signal.get("slug") or "")
    lines = [
        "🚨 Market repricing",
        "",
        q,
        "",
        f"Odds moved: {old_p}% → {new_p}%{delta_str}",
        "",
        "The market sharply repriced expectations.",
        "",
        f"Liquidity: ${liq}",
    ]
    if link:
        lines.append("")
        lines.append(link)
    return "\n".join(lines).strip()


def format_hourly_activity_spike(signal: dict) -> str:
    """News-style: activity spike — trading jumped."""
    q = _clean_text(signal.get("question"))
    old_p = format_number(signal.get("previous_probability"))
    new_p = format_number(signal.get("current_probability"))
    vol = format_number(signal.get("volume_24h"))
    link = _market_url(signal.get("slug") or "")
    lines = [
        "📈 Activity spike",
        "",
        q,
        "",
        f"Odds: {old_p}% → {new_p}%",
        "",
        "Trading activity jumped sharply as traders reposition.",
        "",
        f"24h volume: ${vol}",
    ]
    if link:
        lines.append("")
        lines.append(link)
    return "\n".join(lines).strip()


def format_hourly_trending(signal: dict) -> str:
    """News-style: most active market today."""
    q = _clean_text(signal.get("question"))
    p = format_number(signal.get("current_probability"))
    vol = format_number(signal.get("volume_24h"))
    liq = format_number(signal.get("liquidity"))
    link = _market_url(signal.get("slug") or "")
    lines = [
        "🔥 Most active market today",
        "",
        q,
        "",
        f"Odds: {p}%",
        "",
        f"24h volume: ${vol}",
        f"Liquidity: ${liq}",
    ]
    if link:
        lines.append("")
        lines.append(link)
    return "\n".join(lines).strip()


def format_hourly_post(signal: dict) -> str:
    """Single hourly post: dispatch by signal_type (shock, disagreement, trend, activity_spike, trending)."""
    st = (signal.get("signal_type") or "trending").strip().lower()
    if st == "market_shock":
        return format_hourly_market_shock(signal)
    if st == "market_disagreement":
        return format_hourly_market_disagreement(signal)
    if st == "market_trend":
        return format_hourly_market_trend(signal)
    if st == "activity_spike":
        return format_hourly_activity_spike(signal)
    return format_hourly_trending(signal)


def format_top_moves_section(moves: list[dict]) -> str:
    """Top moves today: numbered list by absolute delta."""
    if not moves:
        return ""
    lines = ["Top moves today", ""]
    for i, row in enumerate(moves, 1):
        q = _clean_text(row.get("question"))
        delta = row.get("delta_24h")
        if delta is not None:
            lines.append(f"{i}. {q} — {delta:+.1f} pp")
        else:
            lines.append(f"{i}. {q}")
    return "\n".join(lines)


def format_daily_digest(
    top_moves: list[dict],
    top_signals: list[dict],
    date_str: str | None = None,
) -> str:
    """Daily digest at 18:00 UTC: 1) Top moves today (by |delta|), 2) Top 6 signals with category and Why it matters."""
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"Polymarket Daily Digest — {date_str}",
        "",
    ]
    # Section 1: Biggest moves (top 5 by absolute delta)
    if top_moves:
        lines.append("1. Biggest prediction market moves today")
        lines.append("")
        lines.append(format_top_moves_section(top_moves))
        lines.append("")
        lines.append("")
    # Section 2: Top 6 signals with category and why it matters
    lines.append("2. Top 6 signals of the day")
    lines.append("")
    if not top_signals:
        lines.append("No signals met the threshold for the last 24 hours.")
    else:
        for i, row in enumerate(top_signals[:6], 1):
            q = _clean_text(row.get("question"))
            old_p = format_number(row.get("previous_probability"))
            new_p = format_number(row.get("current_probability"))
            delta_24h = row.get("delta_24h")
            delta_6h = row.get("delta_6h")
            delta = delta_24h if delta_24h is not None else delta_6h
            delta_str = f" ({delta:+.1f} pp)" if delta is not None else ""
            why = row.get("why_matters") or "Notable move in prediction markets."
            category = (row.get("signal_type") or "signal").replace("_", " ").title()
            lines.append(f"{i}️⃣ {q}")
            lines.append("")
            lines.append(f"Odds: {old_p}% → {new_p}%{delta_str}")
            lines.append(f"[{category}]")
            lines.append(f"Why it matters: {why}")
            if i < min(6, len(top_signals)):
                lines.append("")
                lines.append("---")
                lines.append("")
    return "\n".join(lines).strip()


def format_digest(items: list[dict], use_fallback: bool = False) -> str:
    """Legacy: build digest text; if use_fallback or items empty, return fallback message."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if use_fallback or not items:
        return (
            f"Polymarket Daily Digest — {date_str}\n\n"
            "No major probability moves passed the configured thresholds in the last 24 hours."
        )
    lines = [f"Polymarket Daily Digest — {date_str}\n", "Top moves in the last 24h:\n"]
    for i, row in enumerate(items, 1):
        q = _clean_text(row.get("question"))
        old_p = format_number(row.get("previous_probability"))
        new_p = format_number(row.get("current_probability"))
        delta = row.get("delta_24h")
        delta_str = f" ({delta:+.1f} pp)" if delta is not None else ""
        liq = format_number(row.get("liquidity"))
        vol = format_number(row.get("volume_24h") or row.get("volume"))
        lines.append(f"{i}. {q}")
        lines.append(f"{old_p}% → {new_p}%{delta_str}")
        lines.append(f"Liquidity: {liq}  Volume: {vol}\n")
    return "\n".join(lines).strip()


def _fmt_pct(val: float | None) -> str:
    return f"{format_number(val)}%"


def _fmt_usd(val: float | None) -> str:
    if val is None:
        return "—"
    return f"${int(float(val)):,}".replace(",", " ")


def format_topic_brief(data: dict) -> str:
    topic_ru = data.get("topic_ru") or "Другое"
    top = data.get("top_markets") or []
    biggest = data.get("biggest_move") or {}
    most_active = data.get("most_active") or {}

    gemini_payload = {
        "top_markets": [
            {
                "question": m.get("question"),
                "probability": m.get("current_probability"),
                "delta_24h": m.get("delta_24h"),
                "volume_24h": m.get("volume_24h"),
            }
            for m in top[:3]
        ],
        "biggest_move": {
            "question": biggest.get("question"),
            "delta_24h": biggest.get("delta_24h"),
        },
        "most_active": {
            "question": most_active.get("question"),
            "volume_24h": most_active.get("volume_24h"),
        },
    }
    # Gemini is used only as style rewrite. On any failure we use deterministic template text.
    intro = build_topic_intro_with_gemini(topic_ru, gemini_payload)
    if not intro:
        intro = (
            f"По теме «{topic_ru}» рынок сейчас выделяет несколько ключевых сценариев. "
            "Ниже — рынки с самой высокой уверенностью, заметным движением и наибольшим объемом за сутки."
        )

    lines = [f"Polymarket — {topic_ru}", "", "Что считает рынок:", intro, ""]
    for idx, m in enumerate(top[:3], 1):
        q = _clean_text(m.get("question"))
        old_p = _fmt_pct(m.get("previous_probability"))
        new_p = _fmt_pct(m.get("current_probability"))
        lines.append(f"{idx}. {q}")
        lines.append(f"Вероятность: {new_p}")
        lines.append(f"За 24 часа: {old_p} → {new_p}")
        lines.append("")

    if biggest:
        lines.append("Самое сильное движение за день:")
        lines.append(f"{_clean_text(biggest.get('question'))} — {format_number(biggest.get('delta_24h'))} п.п.")
        lines.append("")
    if most_active:
        lines.append("Самый активный рынок:")
        lines.append(
            f"{_clean_text(most_active.get('question'))} — {_fmt_usd(most_active.get('volume_24h'))} объема за 24 ч"
        )
    return "\n".join(lines).strip()


def format_whale_alert(alert: dict) -> str:
    q = _clean_text(alert.get("question"))
    amount = _fmt_usd(alert.get("amount"))
    p = _fmt_pct(alert.get("current_probability"))
    liq = _fmt_usd(alert.get("liquidity"))
    slug = (alert.get("slug") or "").strip()
    link = _market_url(slug)
    lines = [
        "🐋 Крупная ставка на Polymarket",
        "",
        f"{amount} на рынке:",
        q,
        "",
        f"Текущая вероятность: {p}",
        f"Ликвидность: {liq}",
    ]
    if link:
        lines += ["", link]
    return "\n".join(lines).strip()
