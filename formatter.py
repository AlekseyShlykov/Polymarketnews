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
