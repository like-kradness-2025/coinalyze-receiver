from __future__ import annotations

from typing import Any

from .timeutil import iso_from_ts


def _series_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return [payload]
    return []


def normalize_ohlcv(payload: Any, dataset: str = "ohlcv") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in _series_payload(payload):
        symbol = block.get("symbol") or block.get("s")
        history = block.get("history") or block.get("data") or []
        for item in history:
            ts = item.get("t")
            if ts is None:
                continue
            volume = float(item.get("v") or 0)
            buy_volume = float(item.get("bv") or 0)
            rows.append({
                "dataset": dataset,
                "symbol": symbol,
                "ts": int(ts),
                "time": iso_from_ts(int(ts)),
                "open": float(item.get("o") or 0),
                "high": float(item.get("h") or 0),
                "low": float(item.get("l") or 0),
                "close": float(item.get("c") or 0),
                "volume": volume,
                "buy_volume": buy_volume,
                "sell_volume": volume - buy_volume,
                "delta": 2 * buy_volume - volume,
                "tx": item.get("tx"),
                "buy_tx": item.get("btx"),
            })
    return rows


def normalize_generic_history(payload: Any, dataset: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in _series_payload(payload):
        symbol = block.get("symbol") or block.get("s")
        history = block.get("history") or block.get("data") or []
        for item in history:
            ts = item.get("t")
            if ts is None:
                continue
            row = {
                "dataset": dataset,
                "symbol": symbol,
                "ts": int(ts),
                "time": iso_from_ts(int(ts)),
            }
            for key, value in item.items():
                if key != "t":
                    row[key] = value
            rows.append(row)
    return rows
