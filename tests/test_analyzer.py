"""Tests for analyzer: delta, filtering, ranking."""
import pytest

from analyzer import filter_and_rank, select_digest_markets


def test_filter_by_liquidity():
    items = [
        {"question": "Q1", "delta_24h": 10, "liquidity": 100, "volume": 50},
        {"question": "Q2", "delta_24h": 15, "liquidity": 2000, "volume": 100},
    ]
    out = filter_and_rank(items, min_liquidity=500, min_abs_delta=5, max_items=10)
    assert len(out) == 1
    assert out[0]["question"] == "Q2"
    assert out[0]["liquidity"] == 2000


def test_filter_by_min_abs_delta():
    items = [
        {"question": "Q1", "delta_24h": 3, "liquidity": 1000, "volume": 0},
        {"question": "Q2", "delta_24h": 8, "liquidity": 1000, "volume": 0},
    ]
    out = filter_and_rank(items, min_liquidity=0, min_abs_delta=5, max_items=10)
    assert len(out) == 1
    assert out[0]["delta_24h"] == 8


def test_ranking_by_abs_delta_then_liquidity():
    items = [
        {"question": "Small", "delta_24h": 5, "liquidity": 1000, "volume": 0},
        {"question": "Big", "delta_24h": 20, "liquidity": 500, "volume": 0},
        {"question": "Mid", "delta_24h": 10, "liquidity": 2000, "volume": 0},
    ]
    out = filter_and_rank(items, min_liquidity=0, min_abs_delta=0, max_items=10)
    assert [x["question"] for x in out] == ["Big", "Mid", "Small"]
    assert out[0]["delta_24h"] == 20
    assert out[1]["delta_24h"] == 10
    assert out[2]["delta_24h"] == 5


def test_ranking_tie_break_by_liquidity():
    items = [
        {"question": "Low liq", "delta_24h": 10, "liquidity": 500, "volume": 0},
        {"question": "High liq", "delta_24h": 10, "liquidity": 5000, "volume": 0},
    ]
    out = filter_and_rank(items, min_liquidity=0, min_abs_delta=0, max_items=10)
    assert out[0]["question"] == "High liq"
    assert out[1]["question"] == "Low liq"


def test_max_items_cap():
    items = [
        {"question": f"Q{i}", "delta_24h": 20 - i, "liquidity": 1000, "volume": 0}
        for i in range(5)
    ]
    out = filter_and_rank(items, min_liquidity=0, min_abs_delta=0, max_items=2)
    assert len(out) == 2
    assert out[0]["delta_24h"] == 20
    assert out[1]["delta_24h"] == 19


def test_negative_delta_included_by_abs():
    items = [
        {"question": "Down", "delta_24h": -12, "liquidity": 1000, "volume": 0},
        {"question": "Up", "delta_24h": 8, "liquidity": 1000, "volume": 0},
    ]
    out = filter_and_rank(items, min_liquidity=0, min_abs_delta=5, max_items=10)
    assert len(out) == 2
    assert out[0]["question"] == "Down"
    assert out[1]["question"] == "Up"


def test_select_digest_prefers_fresh_when_possible():
    ranked = [
        {"condition_id": "old1", "question": "A"},
        {"condition_id": "old2", "question": "B"},
        {"condition_id": "new1", "question": "C"},
        {"condition_id": "new2", "question": "D"},
        {"condition_id": "new3", "question": "E"},
        {"condition_id": "new4", "question": "F"},
    ]
    prev = {"old1", "old2"}
    out = select_digest_markets(ranked, prev, 4)
    ids = [x["condition_id"] for x in out]
    assert len(out) == 4
    assert sum(1 for i in ids if i in prev) <= 1
    assert sum(1 for i in ids if i not in prev) >= 3


def test_select_digest_excludes_spotlight_ids():
    ranked = [
        {"condition_id": "spot1", "question": "S1"},
        {"condition_id": "x1", "question": "X1"},
        {"condition_id": "x2", "question": "X2"},
        {"condition_id": "x3", "question": "X3"},
        {"condition_id": "x4", "question": "X4"},
    ]
    out = select_digest_markets(ranked, set(), 4, exclude_condition_ids={"spot1"})
    ids = [x["condition_id"] for x in out]
    assert "spot1" not in ids
    assert len(out) == 4


def test_select_digest_all_new_when_no_history():
    ranked = [{"condition_id": f"n{i}", "question": str(i)} for i in range(4)]
    out = select_digest_markets(ranked, set(), 4)
    assert len(out) == 4


def test_skip_missing_delta():
    items = [
        {"question": "No delta", "delta_24h": None, "liquidity": 5000, "volume": 0},
        {"question": "With delta", "delta_24h": 10, "liquidity": 5000, "volume": 0},
    ]
    out = filter_and_rank(items, min_liquidity=0, min_abs_delta=0, max_items=10)
    assert len(out) == 1
    assert out[0]["question"] == "With delta"
