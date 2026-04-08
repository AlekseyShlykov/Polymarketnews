"""
Lightweight JSON state for 12h cooldown and daily signal accumulation.
Files live in project root; safe for GitHub Actions (checkout + commit back).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parent
STATE_PATH = _ROOT / "state.json"
DAILY_SIGNALS_PATH = _ROOT / "daily_signals.json"
WHALE_ALERTS_PATH = _ROOT / "whale_alerts.json"
DIGEST_ROTATION_PATH = _ROOT / "digest_rotation.json"

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


def append_volume_snapshot(state: dict, volumes: dict[str, float]) -> dict:
    """Append current run's volume24hr snapshot for 6h change later. Keep last 8 hours."""
    state = dict(state)
    snapshots = list(state.get("volume_snapshots") or [])
    snapshots.append({"at": _now_utc().isoformat(), "volumes": {k: float(v) for k, v in volumes.items() if k and v is not None}})
    cutoff = _now_utc() - timedelta(hours=8)
    def _parsed(t):
        try:
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError, AttributeError):
            return None
    snapshots = [s for s in snapshots if isinstance(s, dict) and s.get("at") and _parsed(s.get("at", "")) and _parsed(s["at"]) > cutoff]
    state["volume_snapshots"] = snapshots
    return state


def get_volume_6h_ago(condition_id: str, state: dict) -> float | None:
    """Volume24hr for this market from snapshot closest to 6h ago. For volume_change_6h%."""
    snapshots = state.get("volume_snapshots") or []
    if not isinstance(snapshots, list) or len(snapshots) < 2:
        return None
    now = _now_utc()
    target = now - timedelta(hours=6)
    best = None
    best_diff = None
    for s in snapshots:
        if not isinstance(s, dict):
            continue
        at_str = s.get("at")
        vols = s.get("volumes") or {}
        if not at_str or condition_id not in vols:
            continue
        try:
            at = datetime.fromisoformat(at_str.replace("Z", "+00:00"))
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        diff = abs((at - target).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            try:
                best = float(vols[condition_id])
            except (TypeError, ValueError):
                best = None
    return best


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


def get_top_moves_for_digest(daily_signals: list, max_items: int = 5) -> list[dict]:
    """Top markets by absolute 24h probability move for 'Top moves today' section. Dedupe by condition_id (keep max |delta_24h|)."""
    by_cid: dict[str, dict] = {}
    for s in daily_signals:
        if not isinstance(s, dict):
            continue
        cid = s.get("condition_id") or s.get("slug") or ""
        if not cid:
            continue
        d = s.get("delta_24h")
        abs_d = abs(float(d)) if d is not None else 0
        if cid not in by_cid:
            by_cid[cid] = s
        else:
            existing_d = by_cid[cid].get("delta_24h")
            existing_abs = abs(float(existing_d)) if existing_d is not None else 0
            if abs_d > existing_abs:
                by_cid[cid] = s
    ranked = sorted(
        by_cid.values(),
        key=lambda x: -(abs(float(x.get("delta_24h") or 0))),
    )
    return ranked[:max_items]


def clear_daily_signals_for_new_day() -> None:
    """After sending daily digest, clear so next day starts fresh."""
    save_daily_signals([])


def load_whale_alerts() -> dict:
    """whale_alerts.json storage with backward compatibility."""
    raw = load_json(WHALE_ALERTS_PATH, {})
    if not isinstance(raw, dict):
        return {"alerted": {}, "last_cumulative_volume": {}, "last_checked_at": None}
    # Backward compatibility: old format was plain {alert_id: timestamp}
    if "alerted" not in raw:
        return {"alerted": dict(raw), "last_cumulative_volume": {}, "last_checked_at": None}
    raw.setdefault("last_cumulative_volume", {})
    raw.setdefault("last_checked_at", None)
    return raw


def save_whale_alerts(data: dict) -> None:
    save_json(WHALE_ALERTS_PATH, data)


def is_whale_alerted(alert_id: str) -> bool:
    data = load_whale_alerts()
    return bool((data.get("alerted") or {}).get(alert_id))


def whale_alert_in_cooldown(
    alert_id: str,
    alerted_map: dict,
    cooldown_hours: float,
    *,
    now: datetime | None = None,
) -> bool:
    """True if we already sent a whale alert for this market within cooldown_hours."""
    ts_str = (alerted_map or {}).get(str(alert_id))
    if not ts_str:
        return False
    now = now or _now_utc()
    try:
        at = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    elapsed = (now - at).total_seconds()
    return elapsed < max(0.0, float(cooldown_hours)) * 3600.0


def mark_whale_alerted(alert_id: str) -> None:
    data = load_whale_alerts()
    alerted = dict(data.get("alerted") or {})
    alerted[alert_id] = _now_utc().isoformat()
    # keep file small
    if len(alerted) > 5000:
        items = sorted(alerted.items(), key=lambda x: x[1], reverse=True)[:3000]
        alerted = dict(items)
    data["alerted"] = alerted
    save_whale_alerts(data)


def get_whale_volume_snapshot() -> dict[str, float]:
    """
    Last run's cumulative market volume (Gamma volumeNum), per condition_id.
    Used to compute traded notional since the previous whale check.
    If missing (first deploy after this change), returns {} so the first run rebaselines without false spikes.
    """
    data = load_whale_alerts()
    raw = data.get("last_cumulative_volume")
    if not isinstance(raw, dict) or not raw:
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def set_whale_volume_snapshot(volumes: dict[str, float]) -> None:
    data = load_whale_alerts()
    data["last_cumulative_volume"] = {str(k): float(v) for k, v in volumes.items() if k and v is not None}
    data.pop("last_volume_24h", None)
    data["last_checked_at"] = _now_utc().isoformat()
    save_whale_alerts(data)


def load_digest_rotation() -> dict:
    """Per-topic calendar history of condition_ids shown in digests (UTC dates)."""
    raw = load_json(DIGEST_ROTATION_PATH, {})
    return raw if isinstance(raw, dict) else {}


def save_digest_rotation(data: dict) -> None:
    save_json(DIGEST_ROTATION_PATH, data)


def get_yesterday_digest_condition_ids(topic: str) -> set[str]:
    """
    Condition IDs from the same topic digest on the previous UTC calendar day.
    Used to enforce at most 2 repeats / at least 2 fresh markets.
    """
    topic = (topic or "").strip().lower()
    if not topic:
        return set()
    today = _now_utc().date()
    ykey = (today - timedelta(days=1)).isoformat()
    root = load_digest_rotation()
    entry = root.get(topic)
    if not isinstance(entry, dict):
        return set()
    hist = entry.get("history")
    if not isinstance(hist, dict):
        return set()
    ids = hist.get(ykey)
    if not isinstance(ids, list):
        return set()
    return {str(x) for x in ids if x}


def record_topic_digest_rotation(topic: str, condition_ids: list[str]) -> None:
    """Store today's digest picks for this topic (UTC date)."""
    topic = (topic or "").strip().lower()
    if not topic:
        return
    today_key = _now_utc().date().isoformat()
    root = load_digest_rotation()
    entry = dict(root.get(topic) or {})
    hist = dict(entry.get("history") or {})
    hist[today_key] = [str(x) for x in condition_ids if x]
    # Keep last 4 days to limit file size
    keep_days = sorted(hist.keys(), reverse=True)[:4]
    hist = {k: hist[k] for k in keep_days}
    entry["history"] = hist
    root[topic] = entry
    save_digest_rotation(root)
