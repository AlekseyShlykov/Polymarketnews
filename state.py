"""
Lightweight JSON state for 12h cooldown and daily signal accumulation.
Files live in project root; safe for GitHub Actions (checkout + commit back).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parent
STATE_PATH = _ROOT / "state.json"
DAILY_SIGNALS_PATH = _ROOT / "daily_signals.json"

# Cooldown: do not post same market again within this many hours
COOLDOWN_HOURS = 12


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def load_json(path: Path, default: dict | list) -> dict | list:
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not load %s: %s", path.name, e)
        return default


def save_json(path: Path, data: dict | list) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        logger.warning("Could not save %s: %s", path.name, e)


def load_state() -> dict:
    """state.json: posted[], market_volumes{}."""
    raw = load_json(STATE_PATH, {})
    if not isinstance(raw, dict):
        return {}
    return raw


def save_state(state: dict) -> None:
    save_json(STATE_PATH, state)


def load_daily_signals() -> list:
    """daily_signals.json: list of signal dicts for current day."""
    raw = load_json(DAILY_SIGNALS_PATH, [])
    if not isinstance(raw, list):
        return []
    return raw


def save_daily_signals(signals: list) -> None:
    save_json(DAILY_SIGNALS_PATH, signals)


def is_on_cooldown(condition_id: str, state: dict) -> bool:
    """True if this market was posted in the last COOLDOWN_HOURS."""
    posted = state.get("posted") or []
    if not isinstance(posted, list):
        return False
    cutoff = _now_utc() - timedelta(hours=COOLDOWN_HOURS)
    for entry in posted:
        if not isinstance(entry, dict):
            continue
        if entry.get("condition_id") != condition_id:
            continue
        try:
            at = datetime.fromisoformat(entry.get("posted_at_utc", "").replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at > cutoff:
            return True
    return False


def record_posted(condition_id: str, state: dict) -> dict:
    """Append to posted and prune old entries. Returns updated state."""
    state = dict(state)
    posted = list(state.get("posted") or [])
    cutoff = _now_utc() - timedelta(hours=COOLDOWN_HOURS)
    posted.append({
        "condition_id": condition_id,
        "posted_at_utc": _now_utc().isoformat(),
    })
    # Keep only recent
    def _parsed(t):
        try:
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError, AttributeError):
            return None
    posted = [p for p in posted if isinstance(p, dict) and (p.get("posted_at_utc") and _parsed(p["posted_at_utc"]) and _parsed(p["posted_at_utc"]) > cutoff)]
    state["posted"] = posted
    return state


def get_previous_volume(condition_id: str, state: dict) -> float | None:
    """Last run's volume24hr for this market (for volume_change_1h)."""
    volumes = state.get("market_volumes") or {}
    if not isinstance(volumes, dict):
        return None
    v = volumes.get(condition_id)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def update_market_volumes(state: dict, updates: dict[str, float]) -> dict:
    """Merge volume24hr per condition_id for next run's delta."""
    state = dict(state)
    vol = dict(state.get("market_volumes") or {})
    for cid, val in updates.items():
        if cid and val is not None:
            vol[str(cid)] = float(val)
    state["market_volumes"] = vol
    return state


def add_daily_signal(signal: dict, daily_signals: list) -> list:
    """Append one signal (from hourly run). Dedupe by condition_id kept for daily digest step."""
    out = list(daily_signals)
    out.append(signal)
    return out


def get_daily_signals_for_digest(daily_signals: list, max_items: int = 6) -> list[dict]:
    """Dedupe by condition_id (keep highest score), sort by score desc, return top max_items."""
    by_cid: dict[str, dict] = {}
    for s in daily_signals:
        if not isinstance(s, dict):
            continue
        cid = s.get("condition_id") or s.get("slug") or ""
        if not cid:
            continue
        score = float(s.get("score") or 0)
        if cid not in by_cid or float(by_cid[cid].get("score") or 0) < score:
            by_cid[cid] = s
    ranked = sorted(by_cid.values(), key=lambda x: -(float(x.get("score") or 0)))
    return ranked[:max_items]


def clear_daily_signals_for_new_day() -> None:
    """After sending daily digest, clear so next day starts fresh."""
    save_daily_signals([])
