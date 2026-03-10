"""
Hourly mode: pick exactly 1 best signal per run using score and thresholds.
Uses: combined signal, large prob move, volume spike, new hot market.
Enforces: liquidity >= 5000, 12h cooldown per market.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

import config
from polymarket_client import fetch_all_markets
from state import (
    get_previous_volume,
    is_on_cooldown,
    load_state,
    update_market_volumes,
)

logger = logging.getLogger(__name__)

MIN_LIQ = config.MIN_LIQUIDITY_HOURLY
VOL_CHANGE = config.HOURLY_COMBINED_VOLUME_CHANGE
ABS_DELTA = config.HOURLY_COMBINED_ABS_DELTA_PP
ABS_DELTA_24H = config.HOURLY_LARGE_PROB_MIN_PP_24H
VOL_SPIKE_MIN = config.HOURLY_VOLUME_SPIKE_MIN_USD
NEW_AGE_HOURS = config.HOURLY_NEW_MARKET_AGE_HOURS
NEW_DAILY_VOL = config.HOURLY_NEW_MARKET_DAILY_VOLUME


def _safe_float(val: Any, default: float = 0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _market_age_hours(created_ts: float | None) -> float | None:
    if created_ts is None:
        return None
    try:
        delta = datetime.now(timezone.utc).timestamp() - created_ts
        return delta / 3600.0
    except (TypeError, ValueError):
        return None


def _hourly_volume_usd(volume_24h: float) -> float:
    """Approximate hourly volume from 24h."""
    return volume_24h / 24.0 if volume_24h else 0


def _classify_signal(
    probability_delta_1h: float | None,
    volume_change_1h: float | None,
    hourly_volume_usd: float,
    volume_24h: float,
    market_age_hours: float | None,
    delta_24h: float | None = None,
) -> tuple[bool, bool, bool, bool]:
    """Returns (combined, large_prob, volume_spike, new_hot)."""
    abs_delta = abs(probability_delta_1h or 0)
    vol_ch = volume_change_1h or 0
    combined = vol_ch >= VOL_CHANGE and abs_delta >= ABS_DELTA
    large_prob = abs_delta >= ABS_DELTA or (
        delta_24h is not None and abs(float(delta_24h)) >= ABS_DELTA_24H
    )
    volume_spike = vol_ch >= VOL_CHANGE and hourly_volume_usd >= VOL_SPIKE_MIN
    new_hot = (
        (market_age_hours is not None and market_age_hours < NEW_AGE_HOURS)
        and volume_24h >= NEW_DAILY_VOL
    )
    return combined, large_prob, volume_spike, new_hot


def _score_signal(
    combined: bool,
    large_prob: bool,
    volume_spike: bool,
    new_hot: bool,
    probability_delta_1h: float | None,
    volume_growth_percent: float,
    hourly_volume_usd: float,
    liquidity_usd: float,
) -> float:
    """score = 50*combined + 2*|delta_1h| + 0.8*vol_growth_pct + 0.2*log(hourly_vol+1) + 0.1*log(liq+1)."""
    s = 0.0
    if combined:
        s += 50.0
    s += 2.0 * abs(probability_delta_1h or 0)
    s += 0.8 * volume_growth_percent
    s += 0.2 * math.log(hourly_volume_usd + 1)
    s += 0.1 * math.log(liquidity_usd + 1)
    return s


def _why_matters(combined: bool, large_prob: bool, volume_spike: bool, new_hot: bool, delta_1h: float | None) -> str:
    if combined:
        return "Why this matters: strongest combined price and activity signal in the last hour."
    if large_prob:
        return "Why this matters: biggest standalone probability re-pricing this hour."
    if volume_spike:
        return "Why this matters: largest activity spike in the last hour."
    if new_hot:
        return "Why this matters: fastest-rising new market."
    if (delta_1h or 0) < 0:
        return "Why this matters: notable downside re-pricing this hour."
    return "Why this matters: notable probability move this hour."


def pick_best_hourly_signal() -> tuple[dict | None, dict]:
    """
    Fetch markets, apply thresholds and cooldown, score, return (best_signal, state_updates).
    best_signal is None if no market passes. state_updates: { "market_volumes": { cid: volume24hr } }.
    """
    state = load_state()
    markets = fetch_all_markets(config.MAX_MARKETS_TO_SCAN)
    if not markets:
        logger.warning("No markets from Polymarket")
        return None, {}

    volume_updates = {}
    candidates = []
    n_liq = 0
    n_cooldown = 0
    n_no_qualify = 0
    for m in markets:
        liq = _safe_float(m.get("liquidity"))
        if liq < MIN_LIQ:
            continue
        n_liq += 1
        condition_id = (m.get("condition_id") or m.get("slug") or "").strip()
        if not condition_id:
            continue
        if is_on_cooldown(condition_id, state):
            n_cooldown += 1
            continue
        volume_24h = _safe_float(m.get("volume_24h") or m.get("volume"))
        prev_vol = get_previous_volume(condition_id, state)
        volume_change_1h = (volume_24h - prev_vol) if prev_vol is not None else None
        if volume_change_1h is not None:
            volume_updates[condition_id] = volume_24h
        prob_delta_1h = m.get("probability_delta_1h")
        if prob_delta_1h is not None:
            prob_delta_1h = float(prob_delta_1h)
        # If API has no 1h change, use 24h/24 as proxy so "large prob" can still fire
        if prob_delta_1h is None:
            delta_24h = m.get("delta_24h")
            if delta_24h is not None:
                try:
                    prob_delta_1h = float(delta_24h) / 24.0
                except (TypeError, ValueError):
                    pass
        hourly_vol = _hourly_volume_usd(volume_24h)
        age_hours = _market_age_hours(m.get("created_at_timestamp"))
        delta_24h_val = m.get("delta_24h")
        if delta_24h_val is not None:
            try:
                delta_24h_val = float(delta_24h_val)
            except (TypeError, ValueError):
                delta_24h_val = None
        combined, large_prob, volume_spike, new_hot = _classify_signal(
            prob_delta_1h, volume_change_1h, hourly_vol, volume_24h, age_hours, delta_24h=delta_24h_val
        )
        if not (combined or large_prob or volume_spike or new_hot):
            n_no_qualify += 1
            continue
        vol_growth_pct = 0.0
        if prev_vol and prev_vol > 0 and volume_change_1h is not None:
            vol_growth_pct = (volume_change_1h / prev_vol) * 100
        score = _score_signal(
            combined, large_prob, volume_spike, new_hot,
            prob_delta_1h, vol_growth_pct, hourly_vol, liq,
        )
        why = _why_matters(combined, large_prob, volume_spike, new_hot, prob_delta_1h)
        candidates.append({
            "condition_id": condition_id,
            "question": m.get("question") or "Unknown",
            "slug": m.get("slug") or "",
            "liquidity": liq,
            "volume_24h": volume_24h,
            "volume_change_1h": volume_change_1h,
            "current_probability": m.get("current_probability"),
            "previous_probability": m.get("previous_probability"),
            "probability_delta_1h": prob_delta_1h,
            "delta_24h": m.get("delta_24h"),
            "score": round(score, 2),
            "why_matters": why,
            "combined": combined,
            "large_prob": large_prob,
            "volume_spike": volume_spike,
            "new_hot": new_hot,
        })
    logger.info(
        "Hourly scan: %s markets, %s with liquidity>=%s, %s on cooldown, %s candidates",
        len(markets), n_liq, int(MIN_LIQ), n_cooldown, len(candidates),
    )
    if not candidates:
        state = update_market_volumes(state, volume_updates)
        return None, state
    best = max(candidates, key=lambda x: float(x.get("score") or 0))
    state = update_market_volumes(state, volume_updates)
    return best, state
