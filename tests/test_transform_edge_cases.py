from __future__ import annotations

import pytest

import coinalyze_receiver.transform as transform_mod
from coinalyze_receiver.transform import (
    FootprintLevel,
    build_pseudo_footprint,
    calculate_bucket_poc,
    tick_price,
)


def test_bucket_floor_returns_correct_floor():
    assert transform_mod._bucket_floor(105.7, 10.0) == 100.0
    assert transform_mod._bucket_floor(110.0, 10.0) == 110.0
    assert transform_mod._bucket_floor(100.1, 10.0) == 100.0


def test_touched_price_buckets_raises_for_non_positive_size():
    with pytest.raises(ValueError, match="bucket_size must be positive"):
        transform_mod._touched_price_buckets(100, 110, -1.0)

    with pytest.raises(ValueError, match="bucket_size must be positive"):
        transform_mod._touched_price_buckets(100, 110, 0.0)


def test_bucket_ts_raises_for_non_positive_interval():
    with pytest.raises(ValueError, match="interval_min must be positive"):
        transform_mod._bucket_ts(1700000000, -1)

    with pytest.raises(ValueError, match="interval_min must be positive"):
        transform_mod._bucket_ts(1700000000, 0)


def test_build_pseudo_footprint_returns_empty_dict_for_empty_rows():
    assert build_pseudo_footprint([]) == {}


def test_build_pseudo_footprint_handles_tick_size_zero_by_raising():
    # The internal _touched_price_buckets raises ValueError for non-positive bucket_size
    rows = [
        {"ts": 1700000000, "low": 100, "high": 100, "buy_volume": 10, "sell_volume": 5}
    ]
    with pytest.raises(ValueError, match="bucket_size must be positive"):
        build_pseudo_footprint(rows, tick_size=0.0)


def test_calculate_bucket_poc_returns_none_for_empty_levels():
    assert calculate_bucket_poc([]) is None


def test_tick_price_returns_step():
    assert tick_price() == 1.0
    assert tick_price(0.5) == 0.5


def test_build_pseudo_footprint_uses_lvh_shorthands():
    # Test that _l and _h are used, as well as _v
    rows = [
        {"ts": 1700000000, "l": 100, "h": 120, "v": 30, "bv": 18}
    ]
    fp = build_pseudo_footprint(rows, interval_min=15, tick_size=10)
    levels = list(fp.values())[0]
    assert sum(lv.buy_volume for lv in levels) == 18
    assert sum(lv.sell_volume for lv in levels) == 12


def test_build_pseudo_footprint_handles_single_price_point():
    rows = [
        {"ts": 1700000000, "low": 1000, "high": 1000, "buy_volume": 10, "sell_volume": 5}
    ]
    fp = build_pseudo_footprint(rows, interval_min=15, tick_size=10)
    levels = list(fp.values())[0]
    assert all(lv.price == 1000 for lv in levels)
    assert any(lv.buy_volume + lv.sell_volume > 0 for lv in levels)


def test_build_pseudo_footprint_sorts_output_by_price():
    rows = [
        {"ts": 1700000000, "low": 100, "high": 120, "buy_volume": 10, "sell_volume": 5}
    ]
    fp = build_pseudo_footprint(rows, interval_min=15, tick_size=10)
    levels = list(fp.values())[0]
    prices = [lv.price for lv in levels]
    assert prices == sorted(prices)
