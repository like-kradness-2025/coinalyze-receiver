from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class FootprintLevel:
    price: float
    buy_volume: float
    sell_volume: float
    cvd: float


def _bucket_price(price: float, tick_size: float = 1.0) -> float:
    """指定tick_sizeで価格をバケット化"""
    return round(price / tick_size) * tick_size


def _resample_ohlcv(ohlcv_rows: list[dict[str, Any]], interval_min: int = 15) -> list[dict[str, Any]]:
    """
    1分OHLCVを指定分足にリサンプリング
    volume, buy_volume, delta は合算。open/close は最初/最後、high/low は max/min
    """
    if not ohlcv_rows:
        return []

    # タイムスタンプでソート
    sorted_rows = sorted(ohlcv_rows, key=lambda x: x["ts"])
    
    resampled: list[dict[str, Any]] = []
    current_bucket_ts: int | None = None
    current_data: dict[str, Any] | None = None
    
    interval_sec = interval_min * 60
    
    for row in sorted_rows:
        ts = row["ts"]
        bucket_ts = (ts // interval_sec) * interval_sec
        
        if current_bucket_ts is None or bucket_ts != current_bucket_ts:
            if current_data is not None:
                resampled.append(current_data)
            current_bucket_ts = bucket_ts
            current_data = {
                "ts": bucket_ts,
                "time": row["time"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "buy_volume": row["buy_volume"],
                "sell_volume": row["sell_volume"],
                "delta": row["delta"],
                "tx": row.get("tx", 0),
                "buy_tx": row.get("buy_tx", 0),
            }
        else:
            # current_dataはNoneではないことが保証されている
            if current_data is None:
                continue
            # 価格データ更新
            current_data["high"] = max(current_data["high"], row["high"])
            current_data["low"] = min(current_data["low"], row["low"])
            current_data["close"] = row["close"]
            
            # ボリューム/デルタ合算
            current_data["volume"] = current_data.get("volume", 0) + row.get("volume", 0)
            current_data["buy_volume"] = current_data.get("buy_volume", 0) + row.get("buy_volume", 0)
            current_data["sell_volume"] = current_data.get("sell_volume", 0) + row.get("sell_volume", 0)
            current_data["delta"] = current_data.get("delta", 0) + row.get("delta", 0)
            
            # トランザクション数合算
            current_data["tx"] = current_data.get("tx", 0) + row.get("tx", 0)
            current_data["buy_tx"] = current_data.get("buy_tx", 0) + row.get("buy_tx", 0)
    
    if current_data is not None:
        resampled.append(current_data)
    
    return resampled


def build_pseudo_footprint(
    ohlcv_rows: list[dict[str, Any]],
    interval_min: int = 15,
    tick_size: float = 1.0,
) -> dict[int, list[FootprintLevel]]:
    """
    1分OHLCVから疑似Footprintを構築
    
    戻り値: {bucket_ts: [FootprintLevel, ...]}
    各bucket_tsごとに、価格レベルごとの買/売/CVDを集計
    
    アルゴリズム:
    - まず15分足にリサンプル
    - 各15分足について、high/low間の価格レベルを分解
    - delta (2*buy_volume - volume) を価格レベルに分配
    """
    resampled = _resample_ohlcv(ohlcv_rows, interval_min)
    
    footprint_map: dict[int, list[FootprintLevel]] = {}
    
    for bar in resampled:
        ts = bar["ts"]
        high = bar["high"]
        low = bar["low"]
        total_delta = bar["delta"]
        
        if high <= low:
            continue
        
        num_levels = int((high - low) / tick_size) + 1
        if num_levels <= 0:
            continue
        
        # deltaを価格レベルに均等分配（簡易版）
        delta_per_level = total_delta / num_levels
        
        levels = []
        for i in range(num_levels):
            price = low + i * tick_price(step=tick_size)
            buy_vol = max(0.0, delta_per_level) / 2 if delta_per_level > 0 else 0.0
            sell_vol = abs(delta_per_level) / 2 if delta_per_level < 0 else 0.0
            cvd = delta_per_level
            
            levels.append(FootprintLevel(
                price=price,
                buy_volume=buy_vol,
                sell_volume=sell_vol,
                cvd=cvd,
            ))
        
        footprint_map[ts] = levels
    
    return footprint_map


def tick_price(step: float = 1.0) -> float:
    """Tick step"""
    return step
