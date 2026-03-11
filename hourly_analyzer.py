"""
Hourly mode: pick exactly 1 best signal per run for a prediction-market news bot.

Editorial signal types (priority order for selection):
1) Market shock — very sharp repricing: |delta_3h| >= 15 OR |delta_6h| >= 20.
2) Market disagreement — heavy trading, little move: vol_change_6h >= 70%, |delta_6h| < 3, vol_24h >= 10k.
3) Market trend — steady 24h move: |delta_24h| >= 10 and NOT shock.
4) Activity spike — volume jumped: vol_change_6h >= 70%, vol_24h >= 5k.
5) Trending — fallback: highest daily volume.

Deltas: Gamma API has 1h and 24h. We approximate delta_3h = delta_24h * (3/24), delta_6h = delta_24h * (6/24).
Volume change over 6h uses state volume_snapshots (stored each run).

Score: 60*shock + 45*disagreement + 35*trend + 2*|delta_6h| + 1.2*|delta_24h| + 0.4*vol_change_6h + 0.25*log(vol_24h+1).
Only one post per hour; if no signal passes thresholds we post nothing.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import config
from polymarket_client import fetch_all_markets
from state import (
    append_volume_snapshot,
    get_volume_6h_ago,
    is_on_cooldown,
    load_state,
    update_market_volumes,
)

logger = logging.getLogger(__name__)

MIN_LIQ = config.MIN_LIQUIDITY_HOURLY
SHOCK_3H = config.MARKET_SHOCK_MIN_DELTA_3H_PP
SHOCK_6H = config.MARKET_SHOCK_MIN_DELTA_6H_PP
TREND_24H = config.MARKET_TREND_MIN_DELTA_24H_PP
DISCORD_VOL_PCT = config.MARKET_DISAGREEMENT_VOL_CHANGE_6H_PCT
DISCORD_MAX_DELTA_6H = config.MARKET_DISAGREEMENT_MAX_ABS_DELTA_6H_PP
DISCORD_MIN_VOL = config.MARKET_DISAGREEMENT_MIN_DAILY_VOLUME
ACTIVITY_VOL_PCT = config.ACTIVITY_SPIKE_MIN_VOLUME_CHANGE_6H_PCT
ACTIVITY_MIN_VOL = config.ACTIVITY_SPIKE_MIN_DAILY_VOLUME

# Priority order for hourly selection (lower = higher priority)
_SIGNAL_PRIORITY = {
    "market_shock": 0,
    "market_disagreement": 1,
    "market_trend": 2,
    "activity_spike": 3,
    "trending": 4,
}


def _safe_float(val: Any, default: float = 0) -> float:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _delta_3h_proxy(delta_24h: float | None) -> float:
    """API has no 3h field; approximate from 24h: delta_3h = delta_24h * (3/24)."""
    if delta_24h is None:
        return 0.0
    return float(delta_24h) * (3.0 / 24.0)


def _delta_6h_proxy(delta_24h: float | None) -> float:
    """API has no 6h field; approximate from 24h: delta_6h = delta_24h * (6/24)."""
    if delta_24h is None:
        return 0.0
    return float(delta_24h) * (6.0 / 24.0)


def _is_market_shock(abs_delta_3h: float, abs_delta_6h: float) -> bool:
    return abs_delta_3h >= SHOCK_3H or abs_delta_6h >= SHOCK_6H


def _is_market_trend(abs_delta_24h: float, is_shock: bool) -> bool:
    return abs_delta_24h >= TREND_24H and not is_shock


def _is_market_disagreement(
    volume_change_6h_pct: float | None,
    abs_delta_6h: float,
    volume_24h: float,
) -> bool:
    if volume_change_6h_pct is None:
        return False
    return (
        volume_change_6h_pct >= DISCORD_VOL_PCT
        and abs_delta_6h < DISCORD_MAX_DELTA_6H
        and volume_24h >= DISCORD_MIN_VOL
    )


def _is_activity_spike(volume_change_6h_pct: float | None, volume_24h: float) -> bool:
    if volume_change_6h_pct is None:
        return False
    return volume_change_6h_pct >= ACTIVITY_VOL_PCT and volume_24h >= ACTIVITY_MIN_VOL


def _assign_signal_type(
    is_shock: bool,
    is_disagreement: bool,
    is_trend: bool,
    is_activity: bool,
) -> str:
    """Return highest-priority type this market qualifies for."""
    if is_shock:
        return "market_shock"
    if is_disagreement:
        return "market_disagreement"
    if is_trend:
        return "market_trend"
    if is_activity:
        return "activity_spike"
    return "trending"


def _score_signal(
    signal_type: str,
    delta_6h: float,
    delta_24h: float | None,
    volume_change_6h_pct: float,
    volume_24h: float,
) -> float:
    """score = 60*shock + 45*disagreement + 35*trend + 2*|delta_6h| + 1.2*|delta_24h| + 0.4*vol_change_6h + 0.25*log(vol_24h+1)."""
    base = (
        2.0 * abs(delta_6h)
        + 1.2 * abs(delta_24h or 0)
        + 0.4 * (volume_change_6h_pct or 0)
        + 0.25 * math.log(volume_24h + 1)
    )
    if signal_type == "market_shock":
        return 60.0 + base
    if signal_type == "market_disagreement":
        return 45.0 + base
    if signal_type == "market_trend":
        return 35.0 + base
    if signal_type == "activity_spike":
        return base  # no extra flag weight
    # trending
    return 0.25 * math.log(volume_24h + 1) + 0.1 * abs(delta_6h)


def _why_matters(signal_type: str) -> str:
    if signal_type == "market_shock":
        return "The market repriced sharply in a short period."
    if signal_type == "market_disagreement":
        return "Heavy trading activity did not resolve market disagreement."
    if signal_type == "market_trend":
        return "The market moved steadily over the course of the day."
    if signal_type == "activity_spike":
        return "Trading activity accelerated sharply."
    if signal_type == "trending":
        return "This was one of the most actively traded markets of the day."
    return "Notable move in prediction markets."


def pick_best_hourly_signal() -> tuple[dict | None, dict]:
    """
    Fetch markets, compute deltas (1h, 3h proxy, 6h proxy, 24h) and volume_change_6h,
    classify into shock / disagreement / trend / activity_spike / trending,
    score, apply cooldown. Returns (best_signal, state).
    If no market passes thresholds we post nothing.
    """
    state = load_state()
    markets = fetch_all_markets(config.MAX_MARKETS_TO_SCAN)
    if not markets:
        logger.warning("No markets from Polymarket")
        return None, {}

    volume_updates: dict[str, float] = {}
    candidates: list[dict] = []
    n_liq = 0
    n_cooldown = 0

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
        volume_updates[condition_id] = volume_24h

        delta_24h_raw = m.get("delta_24h")
        delta_24h = float(delta_24h_raw) if delta_24h_raw is not None else None
        delta_6h = _delta_6h_proxy(delta_24h)
        delta_3h = _delta_3h_proxy(delta_24h)
        prob_delta_1h = m.get("probability_delta_1h")
        delta_1h = float(prob_delta_1h) if prob_delta_1h is not None else None
        if delta_1h is None and delta_24h is not None:
            delta_1h = delta_24h / 24.0

        vol_6h_ago = get_volume_6h_ago(condition_id, state)
        volume_change_6h_pct: float | None = None
        if vol_6h_ago is not None and vol_6h_ago > 0:
            volume_change_6h_pct = ((volume_24h - vol_6h_ago) / vol_6h_ago) * 100.0

        abs_delta_3h = abs(delta_3h)
        abs_delta_6h = abs(delta_6h)
        abs_delta_24h = abs(delta_24h or 0)

        is_shock = _is_market_shock(abs_delta_3h, abs_delta_6h)
        is_trend = _is_market_trend(abs_delta_24h, is_shock)
        is_disagreement = _is_market_disagreement(
            volume_change_6h_pct, abs_delta_6h, volume_24h
        )
        is_activity = _is_activity_spike(volume_change_6h_pct, volume_24h)

        signal_type = _assign_signal_type(
            is_shock, is_disagreement, is_trend, is_activity
        )

        # Only add as candidate if it qualifies for something other than pure trending,
        # or we'll add trending later from the full set
        if signal_type != "trending":
            score = _score_signal(
                signal_type,
                delta_6h,
                delta_24h,
                volume_change_6h_pct or 0,
                volume_24h,
            )
            prev_prob = m.get("previous_probability")
            curr_prob = m.get("current_probability")
            candidates.append({
                "condition_id": condition_id,
                "question": m.get("question") or "Unknown",
                "slug": m.get("slug") or "",
                "liquidity": liq,
                "volume_24h": volume_24h,
                "current_probability": curr_prob,
                "previous_probability": prev_prob,
                "probability_delta_1h": delta_1h,
                "delta_24h": delta_24h,
                "delta_6h": delta_6h,
                "delta_3h": delta_3h,
                "volume_change_6h_pct": volume_change_6h_pct,
                "score": round(score, 4),
                "signal_type": signal_type,
                "why_matters": _why_matters(signal_type),
            })
        else:
            # Keep one trending candidate: highest volume_24h (for fallback when no other signals)
            candidates.append({
                "condition_id": condition_id,
                "question": m.get("question") or "Unknown",
                "slug": m.get("slug") or "",
                "liquidity": liq,
                "volume_24h": volume_24h,
                "current_probability": m.get("current_probability"),
                "previous_probability": m.get("previous_probability"),
                "probability_delta_1h": delta_1h,
                "delta_24h": delta_24h,
                "delta_6h": delta_6h,
                "delta_3h": delta_3h,
                "volume_change_6h_pct": volume_change_6h_pct,
                "score": round(_score_signal("trending", delta_6h, delta_24h, volume_change_6h_pct or 0, volume_24h), 4),
                "signal_type": "trending",
                "why_matters": _why_matters("trending"),
            })

    logger.info(
        "Hourly scan: %s markets, %s with liquidity>=%s, %s on cooldown, %s candidates",
        len(markets), n_liq, int(MIN_LIQ), n_cooldown, len(candidates),
    )

    if not candidates:
        state = update_market_volumes(state, volume_updates)
        state = append_volume_snapshot(state, volume_updates)
        return None, state

    # Sort by priority (shock first) then by score descending
    def _rank(c: dict) -> tuple[int, float]:
        prio = _SIGNAL_PRIORITY.get(c.get("signal_type") or "trending", 99)
        return (prio, -(float(c.get("score") or 0)))

    candidates.sort(key=_rank)
    best = candidates[0]

    # If best is trending, only allow when no higher-priority signal exists
    has_higher = any(
        _SIGNAL_PRIORITY.get(c.get("signal_type") or "trending", 99) < _SIGNAL_PRIORITY["trending"]
        for c in candidates
    )
    if best.get("signal_type") == "trending" and has_higher:
        non_trending = [c for c in candidates if c.get("signal_type") != "trending"]
        non_trending.sort(key=lambda c: ( _SIGNAL_PRIORITY.get(c.get("signal_type"), 99), -(float(c.get("score") or 0))))
        best = non_trending[0]

    state = update_market_volumes(state, volume_updates)
    state = append_volume_snapshot(state, volume_updates)
    return best, state
