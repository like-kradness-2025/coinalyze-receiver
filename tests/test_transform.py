from coinalyze_receiver.transform import build_pseudo_footprint, calculate_bucket_poc


def test_build_pseudo_footprint_allocates_1m_rows_into_15m_buckets():
    rows = [
        {
            "ts": 1700000000,
            "time": "2023-11-14T22:13:20+00:00",
            "low": 105023,
            "high": 105087,
            "buy_volume": 70,
            "sell_volume": 35,
        },
        {
            "ts": 1700000060,
            "time": "2023-11-14T22:14:20+00:00",
            "low": 105040,
            "high": 105050,
            "buy_volume": 20,
            "sell_volume": 10,
        },
    ]

    fp = build_pseudo_footprint(rows, interval_min=15, tick_size=10)

    assert len(fp) == 1
    levels = next(iter(fp.values()))
    by_price = {lv.price: lv for lv in levels}

    # First 1m row touches 105020..105080 = 7 buckets.
    expected = {105020, 105030, 105040, 105050, 105060, 105070, 105080}
    assert expected.issubset(by_price.keys())

    # First row allocation only.
    assert by_price[105020].buy_volume == 10
    assert by_price[105020].sell_volume == 5

    # Second row touches 105040 and 105050, adding 10 buy / 5 sell to each.
    assert by_price[105040].buy_volume == 20
    assert by_price[105040].sell_volume == 10
    assert by_price[105050].buy_volume == 20
    assert by_price[105050].sell_volume == 10


def test_calculate_bucket_poc_uses_total_volume():
    rows = [
        {"ts": 1700000000, "low": 100, "high": 100, "buy_volume": 1, "sell_volume": 1},
        {"ts": 1700000060, "low": 110, "high": 110, "buy_volume": 5, "sell_volume": 5},
    ]
    fp = build_pseudo_footprint(rows, interval_min=15, tick_size=10)
    levels = next(iter(fp.values()))
    poc = calculate_bucket_poc(levels)
    assert poc is not None
    assert poc.price == 110


def test_build_pseudo_footprint_supports_raw_like_volume_bv_rows():
    rows = [
        {"ts": 1700000000, "low": 100, "high": 120, "volume": 30, "bv": 18},
    ]
    fp = build_pseudo_footprint(rows, interval_min=15, tick_size=10)
    levels = next(iter(fp.values()))
    assert len(levels) == 3
    assert sum(lv.buy_volume for lv in levels) == 18
    assert sum(lv.sell_volume for lv in levels) == 12
