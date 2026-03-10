"""
Format analyzer output as a concise Telegram digest (template-based).
Handles fallback when there are no strong signals.
"""
from __future__ import annotations

from datetime import datetime, timezone


def format_number(val: float | None) -> str:
    """Format for display; avoid long decimals."""
    if val is None:
        return "—"
    try:
        v = float(val)
        if v == int(v):
            return str(int(v))
        return f"{v:.1f}"
    except (TypeError, ValueError):
        return "—"


def format_hourly_post(signal: dict) -> str:
    """Single hourly signal: headline, question, odds move, volume move, liquidity, why it matters, link."""
    q = (signal.get("question") or "Unknown").strip()
    new_p = format_number(signal.get("current_probability"))
    prev_p = format_number(signal.get("previous_probability"))
    delta = signal.get("probability_delta_1h")
    delta_str = f"{prev_p}% → {new_p}% ({delta:+.1f} pp)" if delta is not None else f"{prev_p}% → {new_p}%"
    vol_ch = signal.get("volume_change_1h")
    vol_str = format_number(vol_ch) if vol_ch is not None else "—"
    liq = format_number(signal.get("liquidity"))
    why = signal.get("why_matters") or "Why this matters: notable move this hour."
    slug = (signal.get("slug") or "").strip()
    link = f"https://polymarket.com/event/{slug}" if slug else ""
    lines = [
        "🔔 Polymarket Hourly Signal",
        "",
        q,
        "",
        f"Odds: {delta_str}",
        f"Volume change (24h delta): {vol_str}",
        f"Liquidity: {liq}",
        "",
        why,
    ]
    if link:
        lines.append("")
        lines.append(link)
    return "\n".join(lines).strip()


def format_daily_digest(signals: list[dict], date_str: str | None = None) -> str:
    """Daily digest at 18:00 UTC: top 6 with question, odds change, volume if relevant, why it matters."""
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not signals:
        return (
            f"Polymarket Daily Digest — {date_str} — 18:00 UTC\n\n"
            "No signals met the threshold for the last 24 hours."
        )
    lines = [f"Polymarket Daily Digest — {date_str} — 18:00 UTC\n"]
    for i, row in enumerate(signals, 1):
        q = (row.get("question") or "Unknown").strip()
        new_p = format_number(row.get("current_probability"))
        prev_p = format_number(row.get("previous_probability"))
        delta_24 = row.get("delta_24h")
        delta_1h = row.get("probability_delta_1h")
        delta = delta_24 if delta_24 is not None else delta_1h
        delta_str = f" ({delta:+.1f} pp)" if delta is not None else ""
        odds_str = f"{prev_p}% → {new_p}%{delta_str}"
        vol_ch = row.get("volume_change_1h")
        vol_str = f" | Vol Δ: {format_number(vol_ch)}" if vol_ch is not None else ""
        why = row.get("why_matters") or "Why it matters: strong move in the last 24h."
        lines.append(f"{i}. {q}")
        lines.append(f"   {odds_str}{vol_str}")
        lines.append(f"   {why}\n")
    return "\n".join(lines).strip()


def format_digest(items: list[dict], use_fallback: bool = False) -> str:
    """
    Build digest text. If use_fallback or items empty, return fallback message.
    """
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if use_fallback or not items:
        return (
            f"Polymarket Daily Digest — {date_str}\n\n"
            "No major probability moves passed the configured thresholds in the last 24 hours."
        )
    lines = [f"Polymarket Daily Digest — {date_str}\n", "Top moves in the last 24h:\n"]
    for i, row in enumerate(items, 1):
        q = (row.get("question") or "Unknown").strip()
        old_p = format_number(row.get("previous_probability"))
        new_p = format_number(row.get("current_probability"))
        delta = row.get("delta_24h")
        delta_str = f" ({delta:+.1f} pp)" if delta is not None else ""
        liq = format_number(row.get("liquidity"))
        vol = format_number(row.get("volume"))
        lines.append(f"{i}. {q}")
        lines.append(f"{old_p}% → {new_p}%{delta_str}")
        lines.append(f"Liquidity: {liq}  Volume: {vol}\n")
    return "\n".join(lines).strip()
