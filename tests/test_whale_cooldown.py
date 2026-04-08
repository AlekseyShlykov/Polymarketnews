"""Whale alert cooldown helper."""
from datetime import datetime, timezone

from state import whale_alert_in_cooldown


def test_whale_alert_in_cooldown_false_when_never_alerted():
    assert not whale_alert_in_cooldown("0xabc", {}, 24.0)


def test_whale_alert_in_cooldown_true_when_recent():
    now = datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)
    alerted = {"0xabc": "2026-04-08T11:00:00+00:00"}
    assert whale_alert_in_cooldown("0xabc", alerted, 24.0, now=now)


def test_whale_alert_in_cooldown_false_after_window():
    now = datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc)
    alerted = {"0xabc": "2026-04-08T11:00:00+00:00"}
    assert not whale_alert_in_cooldown("0xabc", alerted, 24.0, now=now)
