from coinalyze_receiver.normalize import normalize_ohlcv


def test_normalize_ohlcv_delta_fields():
    payload = [
        {
            "symbol": "BTCUSDT_PERP.A",
            "history": [
                {"t": 1700000000, "o": 100, "h": 120, "l": 90, "c": 110, "v": 10, "bv": 7, "tx": 5, "btx": 3}
            ],
        }
    ]
    rows = normalize_ohlcv(payload)
    assert len(rows) == 1
    row = rows[0]
    assert row["buy_volume"] == 7
    assert row["sell_volume"] == 3
    assert row["delta"] == 4
    assert row["symbol"] == "BTCUSDT_PERP.A"
