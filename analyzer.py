"""
Filter and rank markets by 24h probability move and liquidity.
Uses data from Gamma only (current_probability, delta_24h, liquidity).
"""
from __future__ import annotations

import logging
from typing import Any

import config
from polymarket_client import fetch_all_markets

logger = logging.getLogger(__name__)


def _safe_float(val: Any, default: float = 0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def filter_and_rank(
    items: list[dict],
    min_liquidity: float,
    min_abs_delta: float,
    max_items: int,
) -> list[dict]:
    """Keep items with liquidity >= min_liquidity and |delta_24h| >= min_abs_delta; sort by |delta| then liquidity."""
    out = []
    for x in items:
        delta = x.get("delta_24h")
        if delta is None:
            continue
        if _safe_float(x.get("liquidity")) < min_liquidity:
            continue
        if abs(delta) < min_abs_delta:
            continue
        out.append(x)
    out.sort(key=lambda r: (-abs(r.get("delta_24h") or 0), -(r.get("liquidity") or 0)))
    return out[:max_items]


def analyze_markets() -> list[dict]:
    """Fetch markets from Gamma, filter and rank by 24h move. Returns list for formatter."""
    markets = fetch_all_markets(config.MAX_MARKETS_TO_SCAN)
    if not markets:
        logger.warning("No markets returned from Polymarket")
        return []
    ranked = filter_and_rank(
        markets,
        config.MIN_LIQUIDITY,
        config.MIN_ABS_DELTA_24H,
        config.MAX_ITEMS_IN_DIGEST,
    )
    return ranked
