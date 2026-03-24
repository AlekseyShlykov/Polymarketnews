"""
Fetch Polymarket data from Gamma API only.
Parse events/markets defensively; use Gamma's price and oneDayPriceChange (no CLOB).
"""
from __future__ import annotations

import json
import logging
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)


def _safe_float(val: Any, default: float | None = None) -> float | None:
    if val is None:
        return default
    try:
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            return float(val.replace(",", "").strip())
    except (ValueError, TypeError):
        pass
    return default


def _safe_str(val: Any, default: str = "") -> str:
    if val is None:
        return default
    s = str(val).strip()
    return s if s else default


def _parse_token_ids(val: Any) -> list[str]:
    """Parse clobTokenIds: may be JSON string '["id1","id2"]' or list."""
    if isinstance(val, list):
        return [_safe_str(x) for x in val if x]
    if isinstance(val, str) and val.strip():
        try:
            parsed = json.loads(val)
            return [_safe_str(x) for x in parsed] if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def fetch_events(limit: int = 150) -> list[dict]:
    """Fetch active, non-closed events from Gamma."""
    url = f"{config.POLYMARKET_GAMMA_URL}/events?limit={limit}&active=true&closed=false"
    try:
        r = requests.get(url, timeout=config.REQUEST_TIMEOUT_SECONDS)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        logger.warning("Polymarket request failed: %s", e)
        return []
    except (ValueError, TypeError) as e:
        logger.warning("Invalid JSON from Polymarket: %s", e)
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "events", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def event_to_markets(event: dict) -> list[dict]:
    """Extract market rows from one event. Skip closed markets."""
    out = []
    title = _safe_str(event.get("title") or event.get("question"))
    markets_raw = event.get("markets")
    event_category = _safe_str(event.get("category"))
    event_subcategory = _safe_str(event.get("subcategory"))
    event_tags = event.get("tags") if isinstance(event.get("tags"), list) else []
    if not isinstance(markets_raw, list):
        return out
    for m in markets_raw:
        if not isinstance(m, dict):
            continue
        if m.get("closed") is True:
            continue
        question = _safe_str(m.get("question") or m.get("groupItemTitle") or title)
        slug = _safe_str(m.get("slug") or m.get("id"))
        token_ids = _parse_token_ids(m.get("clobTokenIds") or m.get("tokens"))
        if not token_ids:
            continue
        liquidity = _safe_float(m.get("liquidityNum") or m.get("liquidity"), 0) or 0
        volume = _safe_float(m.get("volumeNum") or m.get("volume"), 0) or 0
        # Current price: lastTradePrice or midpoint of bestBid/bestAsk (Gamma provides these)
        last = _safe_float(m.get("lastTradePrice"))
        best_bid = _safe_float(m.get("bestBid"))
        best_ask = _safe_float(m.get("bestAsk"))
        if last is not None:
            current_price = last
        elif best_bid is not None and best_ask is not None:
            current_price = (best_bid + best_ask) / 2
        else:
            # outcomePrices is JSON string like "[\"0.15\", \"0.85\"]" -> first is Yes price
            op = m.get("outcomePrices")
            if isinstance(op, str):
                try:
                    prices = json.loads(op)
                    if isinstance(prices, list) and prices:
                        current_price = _safe_float(prices[0])
                        if current_price is None and len(prices) > 1:
                            current_price = _safe_float(prices[1])
                    else:
                        current_price = None
                except (json.JSONDecodeError, TypeError):
                    current_price = None
            else:
                current_price = None
        if current_price is None or current_price < 0 or current_price > 1:
            continue
        # 24h change in probability (Gamma field; in 0-1 scale, e.g. -0.01 = -1 pp)
        one_day = _safe_float(m.get("oneDayPriceChange"))
        delta_24h = (one_day * 100) if one_day is not None else None
        # 1h change for hourly mode (Gamma: oneHourPriceChange in 0-1)
        one_hour = _safe_float(m.get("oneHourPriceChange"))
        probability_delta_1h = (one_hour * 100) if one_hour is not None else None
        volume_24h = _safe_float(m.get("volume24hr") or m.get("volume24hrClob"), 0) or 0
        condition_id = _safe_str(m.get("conditionId") or m.get("id"))
        # Market age: createdAt or startDate
        created_raw = m.get("createdAt") or m.get("startDate") or event.get("createdAt") or event.get("startDate")
        created_ts = None
        if created_raw:
            try:
                from datetime import datetime as dt, timezone as tz
                if isinstance(created_raw, (int, float)):
                    created_ts = created_raw / 1000 if created_raw > 1e12 else created_raw
                else:
                    created_ts = dt.fromisoformat(str(created_raw).replace("Z", "+00:00")).timestamp()
            except (ValueError, TypeError, OSError):
                pass
        market_tags = m.get("tags") if isinstance(m.get("tags"), list) else []
        tags = [str(t).strip().lower() for t in [*event_tags, *market_tags] if str(t).strip()]
        category = _safe_str(m.get("category") or event_category).lower()
        subcategory = _safe_str(m.get("subcategory") or event_subcategory).lower()
        out.append({
            "question": question or "Unknown",
            "slug": slug,
            "condition_id": condition_id,
            "liquidity": liquidity,
            "volume": volume,
            "volume_24h": volume_24h,
            "current_probability": round(current_price * 100, 1),
            "previous_probability": round((current_price - (one_day or 0)) * 100, 1) if one_day is not None else None,
            "delta_24h": round(delta_24h, 1) if delta_24h is not None else None,
            "probability_delta_1h": round(probability_delta_1h, 1) if probability_delta_1h is not None else None,
            "created_at_timestamp": created_ts,
            "category": category,
            "subcategory": subcategory,
            "tags": tags,
        })
    return out


def fetch_all_markets(max_markets: int | None = None) -> list[dict]:
    """Fetch events and flatten to list of market dicts with price and 24h change."""
    limit = max_markets or config.MAX_MARKETS_TO_SCAN
    events = fetch_events(limit=limit)
    result = []
    seen = set()
    for ev in events:
        if not isinstance(ev, dict):
            continue
        for row in event_to_markets(ev):
            key = (row.get("question"), row.get("slug"))
            if key in seen:
                continue
            seen.add(key)
            result.append(row)
            if len(result) >= limit:
                logger.info("Fetched %s markets from Polymarket", len(result))
                return result
    logger.info("Fetched %s markets from Polymarket", len(result))
    return result
