"""
Core analytics for topic briefs and whale alerts.
Keeps legacy helpers for compatibility with existing tests.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import config
from polymarket_client import fetch_all_markets
from state import (
    load_whale_alerts,
    mark_whale_alerted,
    get_whale_volume_snapshot,
    set_whale_volume_snapshot,
)

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


TOPIC_POLITICS = "politics"
TOPIC_ECONOMY = "economy"
TOPIC_SPORTS = "sports"
TOPIC_OTHER = "other"

TOPIC_LABELS_RU = {
    TOPIC_POLITICS: "Политика",
    TOPIC_ECONOMY: "Экономика",
    TOPIC_SPORTS: "Спорт",
    TOPIC_OTHER: "Другое",
}


def classify_topic(market: dict) -> str:
    """
    Topic classification: category -> subcategory -> tags, otherwise Other.
    """
    category = str(market.get("category") or "").lower()
    subcategory = str(market.get("subcategory") or "").lower()
    tags = [str(t).lower() for t in (market.get("tags") or [])]
    haystack = " ".join([category, subcategory, " ".join(tags)])
    tag_set = set(tags)

    politics_keys = ["politics", "election", "government", "geopolit", "legislation", "leader", "war", "diplom"]
    economy_keys = ["economy", "macro", "inflation", "recession", "fed", "rate", "finance", "crypto", "stock", "commodit"]
    sports_keys = ["sport", "soccer", "football", "nba", "nfl", "tennis", "baseball", "hockey"]
    other_override_tags = {"culture", "pop-culture", "music", "movies", "entertainment", "gta-vi", "celebrity"}

    # If a market is clearly culture/entertainment, prefer Other.
    if tag_set.intersection(other_override_tags):
        return TOPIC_OTHER

    if any(k in haystack for k in politics_keys):
        return TOPIC_POLITICS
    if any(k in haystack for k in economy_keys):
        return TOPIC_ECONOMY
    if any(k in haystack for k in sports_keys):
        return TOPIC_SPORTS
    return TOPIC_OTHER


def _normalize(value: float, min_v: float, max_v: float) -> float:
    if max_v <= min_v:
        return 0.0
    return max(0.0, min(1.0, (value - min_v) / (max_v - min_v)))


def _recency_boost(created_ts: float | None) -> float:
    if not created_ts:
        return 0.0
    age_hours = max(0.0, (datetime.now(timezone.utc).timestamp() - created_ts) / 3600.0)
    if age_hours <= 24:
        return 1.0
    if age_hours <= 72:
        return 0.6
    return 0.2


def _dedupe_near_duplicates(markets: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen = set()
    for m in markets:
        q = str(m.get("question") or "").strip().lower()
        key = " ".join(q.split()[:8])
        if key in seen:
            continue
        seen.add(key)
        out.append(m)
    return out


def _is_recent_market(market: dict, window_hours: float) -> bool:
    created_ts = market.get("created_at_timestamp")
    if created_ts:
        age_hours = (datetime.now(timezone.utc).timestamp() - float(created_ts)) / 3600.0
        if age_hours <= window_hours:
            return True
    # Gamma does not provide a reliable 2h delta, so we use 1h move as a recency proxy.
    one_h = abs(_safe_float(market.get("probability_delta_1h")))
    return one_h >= 0.2


def build_topic_brief_data(
    topic: str,
    max_markets: int | None = None,
    window_hours: float | None = None,
) -> dict:
    """
    Build structured payload for one topic over last 24h.
    """
    markets = fetch_all_markets(max_markets or config.MAX_MARKETS_TO_SCAN)
    topic_rows = []
    for m in markets:
        if classify_topic(m) != topic:
            continue
        if window_hours and window_hours > 0 and not _is_recent_market(m, window_hours):
            continue
        liq = _safe_float(m.get("liquidity"))
        vol24 = _safe_float(m.get("volume_24h") or m.get("volume"))
        if liq < config.TOPIC_MIN_LIQUIDITY or vol24 < config.TOPIC_MIN_VOLUME_24H:
            continue
        if m.get("delta_24h") is None:
            continue
        row = {**m, "liquidity": liq, "volume_24h": vol24}
        if window_hours and window_hours > 0:
            one_h = _safe_float(m.get("probability_delta_1h"))
            delta_period = round(one_h * window_hours, 1)
            current = _safe_float(m.get("current_probability"))
            prev = round(current - delta_period, 1)
            row["display_delta"] = delta_period
            row["display_previous_probability"] = prev
            row["period_label"] = f"{int(window_hours)} часа"
        topic_rows.append(row)

    if not topic_rows:
        # still return compact fallback built from strongest available by liquidity.
        alt = [m for m in markets if classify_topic(m) == topic]
        alt.sort(key=lambda r: (_safe_float(r.get("volume_24h") or r.get("volume")), _safe_float(r.get("liquidity"))), reverse=True)
        topic_rows = [{**m, "liquidity": _safe_float(m.get("liquidity")), "volume_24h": _safe_float(m.get("volume_24h") or m.get("volume"))} for m in alt[: max(3, config.TOPIC_TOP_MARKETS)]]

    vols = [_safe_float(m.get("volume_24h")) for m in topic_rows]
    liqs = [_safe_float(m.get("liquidity")) for m in topic_rows]
    deltas = [abs(_safe_float(m.get("delta_24h"))) for m in topic_rows]

    for m in topic_rows:
        n_vol = _normalize(_safe_float(m.get("volume_24h")), min(vols or [0]), max(vols or [1]))
        n_liq = _normalize(_safe_float(m.get("liquidity")), min(liqs or [0]), max(liqs or [1]))
        n_delta = _normalize(abs(_safe_float(m.get("delta_24h"))), min(deltas or [0]), max(deltas or [1]))
        recency = _recency_boost(m.get("created_at_timestamp"))
        score = (
            config.IMPORTANCE_W_VOLUME * n_vol
            + config.IMPORTANCE_W_LIQUIDITY * n_liq
            + config.IMPORTANCE_W_DELTA * n_delta
            + config.IMPORTANCE_W_RECENCY * recency
        )
        m["importance_score"] = round(score, 4)

    ranked = sorted(topic_rows, key=lambda x: x.get("importance_score", 0), reverse=True)
    ranked = _dedupe_near_duplicates(ranked)
    top3 = ranked[: config.TOPIC_TOP_MARKETS]

    biggest_move = max(ranked, key=lambda x: abs(_safe_float(x.get("delta_24h"))), default=None)
    most_active = max(ranked, key=lambda x: _safe_float(x.get("volume_24h")), default=None)
    return {
        "topic": topic,
        "topic_ru": TOPIC_LABELS_RU.get(topic, "Другое"),
        "top_markets": top3,
        "biggest_move": biggest_move,
        "most_active": most_active,
        "period_label": top3[0].get("period_label") if top3 else "24 часа",
    }


def detect_whale_alerts(max_markets: int | None = None) -> list[dict]:
    """
    Approximation for "trade in last interval":
    compare current volume_24h with previous whale-check snapshot.
    If volume increase over the interval >= threshold, treat as whale-sized trade flow.
    """
    markets = fetch_all_markets(max_markets or config.MAX_MARKETS_TO_SCAN)
    whale_data = load_whale_alerts()
    alerted_map = whale_data.get("alerted") or {}
    previous_snapshot = get_whale_volume_snapshot()
    current_snapshot: dict[str, float] = {}
    alerts: list[dict] = []
    for m in markets:
        alert_id = str(m.get("condition_id") or m.get("slug") or m.get("question") or "")
        vol24 = _safe_float(m.get("volume_24h") or m.get("volume"))
        if alert_id:
            current_snapshot[alert_id] = vol24
        prev_vol24 = previous_snapshot.get(alert_id, vol24)
        interval_volume_delta = max(0.0, vol24 - prev_vol24)
        if interval_volume_delta < config.WHALE_BET_USD_THRESHOLD:
            continue
        if not alert_id or alerted_map.get(alert_id):
            continue
        alerts.append({
            "alert_id": alert_id,
            "amount": round(interval_volume_delta, 0),
            "question": m.get("question") or "Unknown market",
            "current_probability": m.get("current_probability"),
            "liquidity": _safe_float(m.get("liquidity")),
            "slug": m.get("slug") or "",
        })
    alerts.sort(key=lambda x: x["amount"], reverse=True)
    # Always refresh snapshot to represent the most recent 20-minute checkpoint.
    set_whale_volume_snapshot(current_snapshot)
    return alerts


def mark_whale_alert_sent(alert: dict) -> None:
    alert_id = str(alert.get("alert_id") or "")
    if alert_id:
        mark_whale_alerted(alert_id)
