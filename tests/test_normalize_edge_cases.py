from __future__ import annotations

from datetime import datetime, timezone

import pytest

from coinalyze_receiver.normalize import (
    normalize_generic_history,
    normalize_ohlcv,
)
from coinalyze_receiver.timeutil import iso_from_ts


def test_normalize_generic_history_excludes_missing_ts_items():
    payload = [
        {"symbol": "SYM", "history": [{"t": 1700000000, "val": 10}, {"val": 99}, {"t": 1700000060, "val": 20}]}
    ]
    rows = normalize_generic_history(payload, "generic")
    assert len(rows) == 2
    assert rows[0]["ts"] == 1700000000
    assert rows[1]["ts"] == 1700000060


def test_normalize_ohlcv_skips_items_with_null_ts():
    payload = [
        {
            "symbol": "BTC",
            "history": [
                {"t": 1700000000, "o": 1, "h": 2, "l": 1, "c": 2, "v": 10, "bv": 3},
                {"o": 1, "h": 2, "l": 1, "c": 2, "v": 5, "bv": 2},
            ],
        }
    ]
    rows = normalize_ohlcv(payload)
    assert len(rows) == 1
    assert rows[0]["ts"] == 1700000000


def test_normalize_generic_history_handles_dict_payload():
    payload = {"symbol": "ALT", "history": [{"t": 1700000000, "x": 7}]}
    rows = normalize_generic_history(payload, "alt")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "ALT"
    assert rows[0]["x"] == 7


def test_normalize_ohlcv_supports_s_shorthand_symbols():
    payload = {"s": "BID", "history": [{"t": 1700000000, "c": 1, "v": 1, "bv": 0.5}]}
    rows = normalize_ohlcv(payload)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BID"


def test_iso_from_ts_handles_float_timestamp():
    ts = 1700000000.123
    iso = iso_from_ts(ts)
    assert "Z" in iso or "+00:00" in iso
    assert "2023-11-14T22:13:20" in iso
