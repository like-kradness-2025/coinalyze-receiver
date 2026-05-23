from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Any

import numpy as np


@dataclass
class FootprintLevel:
    price: float
    buy_volume: float
    sell_volume: float
    cvd: float


def _bucket_floor(price: float, bucket_size: float) -> float:
    return floor(price / bucket_size) * bucket_size


def _touched_price_buckets(low: float, high: float, bucket_size: float) -> list[float]:
    """Return all price buckets touched by a 1m candle high-low range."""
    if bucket_size <= 0:
        raise ValueError("bucket_size must be positive")

    lo = min(float(low), float(high))
    hi = max(float(low), float(high))

    start = _bucket_floor(lo, bucket_size)
    end = _bucket_floor(hi, bucket_size)
    count = int(round((end - start) / bucket_size)) + 1
    return [start + i * bucket_size for i in range(max(count, 1))]


def _bucket_ts(ts: int, interval_min: int) -> int:
    if interval_min <= 0:
        raise ValueError("interval_min must be positive")
    interval_sec = interval_min * 60
    return int(ts // interval_sec * interval_sec)


def build_pseudo_footprint(
    ohlcv_rows: list[dict[str, Any]],
    interval_min: int = 15,
    tick_size: float = 10.0,
) -> dict[int, list[FootprintLevel]]:
    """
    Build a Coinalyze OHLCV-based pseudo footprint.

    Important:
    This is not a true tick-level footprint.

    Algorithm:
    - Use each 1m OHLCV row independently.
    - buy_volume = bv-derived normalized field.
    - sell_volume = v - bv-derived normalized field.
    - Split the 1m high-low range into price buckets.
    - Uniformly distribute buy/sell volume into touched buckets.
    - Aggregate those allocations into interval_min buckets, default 15m.

    Return:
    {bar_ts: [FootprintLevel(price=bucket, buy_volume=..., sell_volume=..., cvd=...), ...]}
    """
    if not ohlcv_rows:
        return {}

    # {interval_ts: {price_bucket: {buy, sell}}}
    agg: dict[int, dict[float, dict[str, float]]] = {}

    seen_keys: set[tuple[str, str, int]] = set()
    for row in sorted(ohlcv_rows, key=lambda x: int(x["ts"])):
        dataset = str(row.get("dataset", "ohlcv"))
        symbol = str(row.get("symbol", ""))
        ts = int(row["ts"])
        dedupe_key = (dataset, symbol, ts)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        low = float(row.get("low", row.get("l", 0.0)) or 0.0)
        high = float(row.get("high", row.get("h", low)) or low)
        buy_volume = float(row.get("buy_volume", row.get("bv", 0.0)) or 0.0)
        sell_volume = float(row.get("sell_volume", 0.0) or 0.0)

        # Fallback for raw-like rows where only volume/bv are available.
        if "sell_volume" not in row:
            volume = float(row.get("volume", row.get("v", 0.0)) or 0.0)
            sell_volume = max(volume - buy_volume, 0.0)

        buckets = _touched_price_buckets(low, high, tick_size)
        if not buckets:
            continue

        buy_each = buy_volume / len(buckets)
        sell_each = sell_volume / len(buckets)
        bar_ts = _bucket_ts(ts, interval_min)
        dst = agg.setdefault(bar_ts, {})

        for price in buckets:
            level = dst.setdefault(price, {"buy": 0.0, "sell": 0.0})
            level["buy"] += buy_each
            level["sell"] += sell_each

    footprint: dict[int, list[FootprintLevel]] = {}
    for bar_ts, levels in sorted(agg.items()):
        footprint[bar_ts] = [
            FootprintLevel(
                price=price,
                buy_volume=values["buy"],
                sell_volume=values["sell"],
                cvd=values["buy"] - values["sell"],
            )
            for price, values in sorted(levels.items())
        ]

    return footprint


def calculate_bucket_poc(levels: list[FootprintLevel]) -> FootprintLevel | None:
    """Return the highest total-volume pseudo footprint level."""
    if not levels:
        return None
    return max(levels, key=lambda lv: lv.buy_volume + lv.sell_volume)


# Backward-compatible alias for old callers/tests.
def tick_price(step: float = 1.0) -> float:
    return step
