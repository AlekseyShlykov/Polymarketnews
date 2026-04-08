"""
Core analytics for topic briefs and whale alerts.
Keeps legacy helpers for compatibility with existing tests.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import config
from polymarket_client import fetch_all_markets
from state import (
    get_whale_volume_snapshot,
    get_yesterday_digest_condition_ids,
    load_whale_alerts,
    mark_whale_alerted,
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


# Tag slugs/labels (lowercase) that strongly imply a bucket — checked before substring heuristics.
_POLITICS_TAG_SLUGS = frozenset({
    "politics", "political", "geopolitics", "geopolitical", "world", "elections", "global-elections",
    "us-election", "world-elections", "trump", "biden", "congress", "senate", "house",
    "foreign-policy", "international-relations", "diplomacy", "nato", "united-nations",
    "ukraine", "russia", "israel", "palestine", "iran", "middle-east", "gaza", "syria",
    "china", "taiwan", "india", "pakistan", "north-korea", "south-korea", "japan",
    "defense", "military", "conflict", "war", "ceasefire", "cease-fire", "sanctions", "summit",
    "macron", "starmer", "eu-politics", "brexit", "election", "parliament",
    "hormuz", "strait-of-hormuz", "red-sea", "bab-el-mandeb", "chokepoint", "maritime",
    "regime-change", "regime-collapse", "government-collapse", "iran-nuclear",
})
_ECONOMY_TAG_SLUGS = frozenset({
    "economy", "economic", "macro", "inflation", "recession", "fed", "interest-rates",
    "finance", "crypto", "bitcoin", "ethereum", "stocks", "equities", "commodities",
    "gdp", "employment", "jobs", "banking", "treasury", "yield", "rates", "forex",
    "ipo", "earnings", "markets", "defi", "nft",
})
_SPORTS_TAG_SLUGS = frozenset({
    "sports", "sport", "soccer", "football", "nba", "nfl", "mlb", "nhl", "tennis",
    "baseball", "hockey", "ufc", "mma", "boxing", "olympics", "f1", "formula-1",
    "esports", "ncaa", "golf", "cricket", "rugby",
})

# Substrings in category + subcategory + tags (joined) — longer phrases first where possible.
_POLITICS_SUBSTR = (
    "geopolit", "foreign policy", "foreign-policy", "united nations", "legislation",
    "government shutdown", "white house", "kremlin", "nato", "sanction", "ceasefire",
    "cease fire", "cease-fire", "truce", "de-escalation", "deescalation",
    "invasion", "military", "diplom", "embassy", "ambassador", "treaty", "summit",
    "referendum", "parliament", "congressional", "senate race", "presidential",
    "ukraine", "russia", "zelensky", "putin", "iran", "tehran", "israel", "palestine", "gaza",
    "middle east", "persian gulf", "arabian gulf", "strait of hormuz", "hormuz",
    "bab el-mandeb", "red sea", "suez", "chokepoint", "south china sea", "taiwan strait",
    "north korea", "ballistic",
    "crimea", "donbas", "humanitarian", "coup", "insurg", "terror", "border",
    "territory", "occupation", "peace deal", "two-state", "settlements", "hezbollah",
    "houthis", "yemen", "syria", "lebanon", "iraq", "afghanistan", "libya", "sudan",
    "sub-saharan", "africa politics", "latin america politics", "election", "electoral",
    "impeach", "cabinet", "prime minister", "chancellor", "dictator", "authoritarian",
    "regime change", "regime fall", "regime collapse", "government collapse", "fall of",
    "oust", "step down", "mobilization", "mobilisation", "martial law", "annexation",
    "recognition of", "breakaway", "separatist", "insurrection",
)
_ECONOMY_SUBSTR = (
    "economy", "macro", "inflation", "recession", "fed ", "federal reserve", "interest rate",
    "cpi ", "gdp", "jobs report", "nonfarm", "treasury", "yield curve", "banking",
    "finance", "crypto", "bitcoin", "ethereum", "stock", "equity", "commodit", "oil price",
    "natural gas", "gold price", "forex", "dollar index", "ipo", "earnings", "merger",
    "acquisition", "bankruptcy", "default", "bailout", "stimulus", "tariff", "trade war",
)
_SPORTS_SUBSTR = (
    "sport", "soccer", "football", "nba", "nfl", "mlb", "nhl", "tennis", "baseball",
    "hockey", "ufc", "mma", "boxing", "olympic", "f1", "formula 1", "esports", "ncaa",
    "premier league", "champions league", "world cup", "super bowl", "stanley cup",
    "wimbledon", "golf", "cricket", "rugby", "nascar",
)


def classify_topic(market: dict) -> str:
    """
    Topic classification: explicit culture override, then tag hints, then substring heuristics.
    """
    category = str(market.get("category") or "").lower()
    subcategory = str(market.get("subcategory") or "").lower()
    tags = [str(t).lower() for t in (market.get("tags") or [])]
    haystack = " ".join([category, subcategory, " ".join(tags)])
    tag_set = set(tags)

    other_override_tags = {"culture", "pop-culture", "music", "movies", "entertainment", "gta-vi", "celebrity", "awards"}

    if tag_set.intersection(other_override_tags):
        return TOPIC_OTHER

    if tag_set.intersection(_POLITICS_TAG_SLUGS):
        return TOPIC_POLITICS
    if any(s in haystack for s in _POLITICS_SUBSTR):
        return TOPIC_POLITICS

    if tag_set.intersection(_ECONOMY_TAG_SLUGS):
        return TOPIC_ECONOMY
    if any(s in haystack for s in _ECONOMY_SUBSTR):
        return TOPIC_ECONOMY

    if tag_set.intersection(_SPORTS_TAG_SLUGS):
        return TOPIC_SPORTS
    if any(s in haystack for s in _SPORTS_SUBSTR):
        return TOPIC_SPORTS

    return TOPIC_OTHER


# Crypto-heavy economy markets (Fed / recession / equities stay non-crypto).
_CRYPTO_TAG_SLUGS = frozenset({
    "crypto", "bitcoin", "ethereum", "defi", "nft", "solana", "altcoin", "dogecoin",
    "chainlink", "polygon", "matic", "avalanche", "cardano", "xrp", "ripple",
    "microstrategy", "coinbase", "bitcoin-etf", "spot-bitcoin", "memecoin",
    "web3", "layer-2", "layer2", "stablecoin", "cbdc",
})
_CRYPTO_SUBSTR = (
    "bitcoin", "btc ", " btc", "ethereum", "eth ", " ether", "solana", "defi",
    "nft ", "crypto ", "stablecoin", " usdt", " usdc", "dogecoin", "shiba",
    "microstrategy", "coinbase", " grayscale", "spot etf", "bitcoin etf",
    "layer 2", "layer-2", "altcoin", "memecoin", "proof-of-stake", "proof of stake",
    "satoshi", "halving", "on-chain", "defi ", "yield farm",
)


def is_crypto_economy_market(market: dict) -> bool:
    """True if market is treated as crypto-themed (for economy digest caps)."""
    tags = [str(t).lower() for t in (market.get("tags") or [])]
    tag_set = set(tags)
    if tag_set.intersection(_CRYPTO_TAG_SLUGS):
        return True
    q = str(market.get("question") or "").lower()
    cat = str(market.get("category") or "").lower()
    sub = str(market.get("subcategory") or "").lower()
    hay = " ".join([cat, sub, " ".join(tags), q])
    return any(s in hay for s in _CRYPTO_SUBSTR)


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


def select_digest_markets(
    ranked: list[dict],
    prev_ids: set[str],
    count: int,
    *,
    exclude_condition_ids: set[str] | None = None,
    max_repeat_from_prev: int | None = None,
) -> list[dict]:
    """
    Pick `count` markets in global rank order with rotation vs yesterday:
    at most `max_repeat_from_prev` from prev_ids, at least (count - that) new when possible.
    Skips any condition_id in exclude_condition_ids (e.g. politics spotlight markets).
    """
    if count <= 0:
        return []
    prev_ids = {str(x) for x in (prev_ids or set()) if x}
    exclude = {str(x) for x in (exclude_condition_ids or set()) if x}
    max_rep = max_repeat_from_prev
    if max_rep is None:
        max_rep = int(getattr(config, "TOPIC_DIGEST_MAX_REPEAT_PREVIOUS_DAY", 1))
    max_rep = max(0, min(max_rep, count))
    min_new_required = max(0, count - max_rep)

    def cid(m: dict) -> str:
        return str(m.get("condition_id") or "")

    selected: list[dict] = []
    selected_ids: set[str] = set()

    for m in ranked:
        if len(selected) >= count:
            break
        c = cid(m)
        if not c or c in selected_ids or c in exclude:
            continue
        n_old = sum(1 for x in selected if cid(x) in prev_ids)
        n_new = len(selected) - n_old
        is_old = c in prev_ids
        slots_left = count - len(selected)
        if is_old:
            if n_old >= max_rep:
                continue
            remaining_after = slots_left - 1
            need_new = max(0, min_new_required - n_new)
            if need_new > remaining_after:
                continue
        selected.append(m)
        selected_ids.add(c)

    if len(selected) < count:
        for m in ranked:
            if len(selected) >= count:
                break
            c = cid(m)
            if not c or c in selected_ids or c in exclude or c in prev_ids:
                continue
            selected.append(m)
            selected_ids.add(c)

    if len(selected) < count:
        for m in ranked:
            if len(selected) >= count:
                break
            c = cid(m)
            if not c or c in selected_ids or c in exclude:
                continue
            n_old = sum(1 for x in selected if cid(x) in prev_ids)
            if c in prev_ids and n_old >= max_rep:
                continue
            n_new = len(selected) - n_old
            slots_left = count - len(selected)
            if c in prev_ids:
                remaining_after = slots_left - 1
                need_new = max(0, min_new_required - n_new)
                if need_new > remaining_after:
                    continue
            selected.append(m)
            selected_ids.add(c)

    if len(selected) < count:
        for m in ranked:
            if len(selected) >= count:
                break
            c = cid(m)
            if not c or c in selected_ids or c in exclude:
                continue
            selected.append(m)
            selected_ids.add(c)

    return selected[:count]


def _digest_candidate_ok(
    m: dict,
    selected: list[dict],
    prev_ids: set[str],
    count: int,
    max_rep: int,
    exclude: set[str],
) -> bool:
    def cid(x: dict) -> str:
        return str(x.get("condition_id") or "")

    c = cid(m)
    if not c or c in exclude:
        return False
    if any(cid(x) == c for x in selected):
        return False
    min_new = max(0, count - max_rep)
    n_old = sum(1 for x in selected if cid(x) in prev_ids)
    n_new = len(selected) - n_old
    is_old = c in prev_ids
    slots_left = count - len(selected)
    if is_old:
        if n_old >= max_rep:
            return False
        remaining_after = slots_left - 1
        need_new = max(0, min_new - n_new)
        if need_new > remaining_after:
            return False
    return True


def select_economy_digest_markets(
    ranked_for_top: list[dict],
    prev_ids: set[str],
    count: int,
    exclude_condition_ids: set[str] | None = None,
) -> list[dict]:
    """
    Economy top-N: positions 1–2 are non-crypto macro; at most ECONOMY_DIGEST_MAX_CRYPTO
    crypto items in the full list; same yesterday-rotation rules as select_digest_markets.
    """
    if count <= 0:
        return []
    exclude = {str(x) for x in (exclude_condition_ids or set()) if x}
    prev_ids = {str(x) for x in (prev_ids or set()) if x}
    max_rep = int(getattr(config, "TOPIC_DIGEST_MAX_REPEAT_PREVIOUS_DAY", 1))
    max_crypto = int(getattr(config, "ECONOMY_DIGEST_MAX_CRYPTO", 2))

    def cid(x: dict) -> str:
        return str(x.get("condition_id") or "")

    selected: list[dict] = []

    while len(selected) < 2 and len(selected) < count:
        added = False
        for m in ranked_for_top:
            if is_crypto_economy_market(m):
                continue
            if not _digest_candidate_ok(m, selected, prev_ids, count, max_rep, exclude):
                continue
            selected.append(m)
            added = True
            break
        if not added:
            break

    while len(selected) < count:
        added = False
        for m in ranked_for_top:
            c = cid(m)
            if not c or c in exclude or c in {cid(x) for x in selected}:
                continue
            if is_crypto_economy_market(m):
                if sum(1 for x in selected if is_crypto_economy_market(x)) >= max_crypto:
                    continue
            if not _digest_candidate_ok(m, selected, prev_ids, count, max_rep, exclude):
                continue
            selected.append(m)
            added = True
            break
        if not added:
            break

    while len(selected) < count:
        added = False
        for m in ranked_for_top:
            c = cid(m)
            if not c or c in exclude or c in {cid(x) for x in selected}:
                continue
            if len(selected) < 2 and is_crypto_economy_market(m):
                continue
            if is_crypto_economy_market(m):
                if sum(1 for x in selected if is_crypto_economy_market(x)) >= max_crypto:
                    continue
            selected.append(m)
            added = True
            break
        if not added:
            break

    if len(selected) < count:
        for m in ranked_for_top:
            if len(selected) >= count:
                break
            c = cid(m)
            if not c or c in exclude or c in {cid(x) for x in selected}:
                continue
            if len(selected) < 2 and is_crypto_economy_market(m):
                continue
            if is_crypto_economy_market(m):
                if sum(1 for x in selected if is_crypto_economy_market(x)) >= max_crypto:
                    continue
            selected.append(m)

    return selected[:count]


def _build_topic_event_spotlight(
    all_markets: list[dict],
    topic: str,
    *,
    market_include: Callable[[dict], bool] | None = None,
) -> dict | None:
    """
    Multi-outcome event (same event_id) with highest total liquidity across sibling markets.
    Optional market_include(m) — if False, skip market (e.g. exclude crypto for economy spotlight).
    """
    from collections import defaultdict

    by_event: dict[str, list[dict]] = defaultdict(list)
    for m in all_markets:
        if classify_topic(m) != topic:
            continue
        if market_include is not None and not market_include(m):
            continue
        evid = str(m.get("event_id") or "").strip()
        if not evid:
            continue
        liq = _safe_float(m.get("liquidity"))
        vol24 = _safe_float(m.get("volume_24h") or m.get("volume"))
        if liq < config.TOPIC_MIN_LIQUIDITY or vol24 < config.TOPIC_MIN_VOLUME_24H:
            continue
        if m.get("current_probability") is None:
            continue
        by_event[evid].append(m)

    best_ms: list[dict] | None = None
    best_total_liq = -1.0
    for ms in by_event.values():
        if len(ms) < config.POLITICS_SPOTLIGHT_MIN_MARKETS:
            continue
        total_liq = sum(_safe_float(x.get("liquidity")) for x in ms)
        if total_liq > best_total_liq:
            best_total_liq = total_liq
            best_ms = ms

    if not best_ms:
        return None

    ms_sorted = sorted(
        best_ms,
        key=lambda x: (str(x.get("end_date") or ""), str(x.get("question") or "")),
    )
    cap = config.POLITICS_SPOTLIGHT_MAX_LINES
    return {
        "event_title": (ms_sorted[0].get("event_title") or "").strip() or "—",
        "event_slug": (ms_sorted[0].get("slug") or "").strip(),
        "total_liquidity": round(best_total_liq, 0),
        "markets": ms_sorted[:cap],
    }


def build_politics_event_spotlight(all_markets: list[dict]) -> dict | None:
    """Politics digest: multi-deadline event spotlight."""
    return _build_topic_event_spotlight(all_markets, TOPIC_POLITICS, market_include=None)


def build_economy_event_spotlight(all_markets: list[dict]) -> dict | None:
    """Economy digest: same block, only non-crypto macro economy events."""
    return _build_topic_event_spotlight(
        all_markets,
        TOPIC_ECONOMY,
        market_include=lambda m: not is_crypto_economy_market(m),
    )


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
            prev = max(0.0, min(100.0, prev))
            row["display_delta"] = delta_period
            row["display_previous_probability"] = prev
            row["period_label"] = f"{int(window_hours)} часа"
        topic_rows.append(row)

    if not topic_rows:
        # still return compact fallback built from strongest available by liquidity.
        alt = [m for m in markets if classify_topic(m) == topic]
        alt.sort(key=lambda r: (_safe_float(r.get("volume_24h") or r.get("volume")), _safe_float(r.get("liquidity"))), reverse=True)
        topic_rows = [{**m, "liquidity": _safe_float(m.get("liquidity")), "volume_24h": _safe_float(m.get("volume_24h") or m.get("volume"))} for m in alt[: max(4, config.TOPIC_TOP_MARKETS)]]

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
    use_rotation = not (window_hours and window_hours > 0)
    prev_ids = get_yesterday_digest_condition_ids(topic) if use_rotation else set()
    event_spotlight = None
    if use_rotation and topic == TOPIC_POLITICS:
        event_spotlight = build_politics_event_spotlight(markets)
    elif use_rotation and topic == TOPIC_ECONOMY:
        event_spotlight = build_economy_event_spotlight(markets)

    spotlight_cids: set[str] = set()
    if isinstance(event_spotlight, dict):
        for sm in event_spotlight.get("markets") or []:
            sc = str(sm.get("condition_id") or "").strip()
            if sc:
                spotlight_cids.add(sc)
    ranked_for_top = [m for m in ranked if str(m.get("condition_id") or "").strip() not in spotlight_cids]
    if use_rotation:
        if topic == TOPIC_ECONOMY:
            top_n = select_economy_digest_markets(
                ranked_for_top,
                prev_ids,
                config.TOPIC_TOP_MARKETS,
                exclude_condition_ids=spotlight_cids,
            )
        else:
            top_n = select_digest_markets(
                ranked_for_top,
                prev_ids,
                config.TOPIC_TOP_MARKETS,
                exclude_condition_ids=spotlight_cids,
            )
    else:
        top_n = ranked_for_top[: config.TOPIC_TOP_MARKETS]

    biggest_move = max(ranked, key=lambda x: abs(_safe_float(x.get("delta_24h"))), default=None)
    most_active = max(ranked, key=lambda x: _safe_float(x.get("volume_24h")), default=None)
    return {
        "topic": topic,
        "topic_ru": TOPIC_LABELS_RU.get(topic, "Другое"),
        "top_markets": top_n,
        "biggest_move": biggest_move,
        "most_active": most_active,
        "period_label": top_n[0].get("period_label") if top_n else "24 часа",
        "event_spotlight": event_spotlight,
        "record_rotation": use_rotation,
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
        tpc = classify_topic(m)
        if tpc == TOPIC_OTHER:
            continue
        if tpc == TOPIC_SPORTS:
            threshold = config.WHALE_SPORTS_OTHER_USD_THRESHOLD
        else:
            threshold = config.WHALE_BET_USD_THRESHOLD
        if interval_volume_delta < threshold:
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
