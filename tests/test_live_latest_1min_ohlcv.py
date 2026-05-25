"""Live smoke test for latest Coinalyze 1-minute OHLCV.

This test intentionally calls the real Coinalyze REST API.
It is skipped unless COINALYZE_API_KEY is set.

Purpose:
- Fetch only the latest closed 1-minute OHLCV period.
- Test around three symbols.
- Print UTC/JST timestamps and lag seconds to check whether the data is truly delayed
  or only appears shifted by timezone handling.

Run:
    COINALYZE_API_KEY=... pytest -q -s tests/test_live_latest_1min_ohlcv.py

Optional symbols override:
    COINALYZE_LIVE_TEST_SYMBOLS=BTCUSDT_PERP.A,ETHUSDT_PERP.A,SOLUSDT_PERP.A \
      pytest -q -s tests/test_live_latest_1min_ohlcv.py
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest


BASE_URL = "https://api.coinalyze.net/v1/ohlcv-history"
DEFAULT_SYMBOLS = (
    "BTCUSDT_PERP.A",
    "ETHUSDT_PERP.A",
    "SOLUSDT_PERP.A",
)


def _latest_closed_1m_window(now: datetime | None = None) -> tuple[int, int]:
    """Return latest fully closed 1-minute candle window as UNIX seconds."""
    now = now or datetime.now(timezone.utc)
    end_dt = now.replace(second=0, microsecond=0)
    start_dt = end_dt - timedelta(minutes=1)
    return int(start_dt.timestamp()), int(end_dt.timestamp())


def _symbols_from_env() -> list[str]:
    raw = os.getenv("COINALYZE_LIVE_TEST_SYMBOLS", "")
    if raw.strip():
        symbols = [s.strip() for s in raw.split(",") if s.strip()]
    else:
        symbols = list(DEFAULT_SYMBOLS)
    return symbols[:3]


def _fetch_ohlcv_history(api_key: str, symbol: str, from_ts: int, to_ts: int) -> Any:
    params = urllib.parse.urlencode(
        {
            "symbols": symbol,
            "interval": "1min",
            "from": from_ts,
            "to": to_ts,
        }
    )
    request = urllib.request.Request(
        f"{BASE_URL}?{params}",
        headers={"api_key": api_key},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    blocks = payload if isinstance(payload, list) else [payload]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        symbol = block.get("symbol")
        history = block.get("history") or []
        for row in history:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            item["symbol"] = symbol
            rows.append(item)
    return rows


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("COINALYZE_API_KEY"), reason="COINALYZE_API_KEY is not set")
def test_fetch_latest_closed_1min_ohlcv_for_three_symbols() -> None:
    api_key = os.environ["COINALYZE_API_KEY"]
    symbols = _symbols_from_env()
    assert len(symbols) == 3

    from_ts, to_ts = _latest_closed_1m_window()
    from_utc = datetime.fromtimestamp(from_ts, tz=timezone.utc)
    to_utc = datetime.fromtimestamp(to_ts, tz=timezone.utc)

    print()
    print("Coinalyze latest closed 1m OHLCV smoke test")
    print(f"request_window_utc: {from_utc.isoformat()} -> {to_utc.isoformat()}")
    print("symbol,last_t_utc,last_t_jst,lag_sec,open,high,low,close,volume,buy_volume")

    for symbol in symbols:
        payload = _fetch_ohlcv_history(api_key, symbol, from_ts, to_ts)
        rows = _extract_rows(payload)
        assert rows, f"no OHLCV rows returned for {symbol} in {from_ts}->{to_ts}: {payload}"

        latest = max(rows, key=lambda row: int(row["t"]))
        last_t = int(latest["t"])
        last_utc = datetime.fromtimestamp(last_t, tz=timezone.utc)
        last_jst = last_utc.astimezone(timezone(timedelta(hours=9)))
        lag_sec = int(datetime.now(timezone.utc).timestamp()) - last_t

        print(
            f"{symbol},"
            f"{last_utc.isoformat()},"
            f"{last_jst.isoformat()},"
            f"{lag_sec},"
            f"{latest.get('o')},"
            f"{latest.get('h')},"
            f"{latest.get('l')},"
            f"{latest.get('c')},"
            f"{latest.get('v')},"
            f"{latest.get('bv')}"
        )

        # If this fails with ~32400 seconds, it strongly suggests real data delay.
        # If JST is current while UTC appears 9h behind, it is only timezone handling.
        assert lag_sec < 30 * 60, f"{symbol} latest 1m OHLCV looks stale: lag_sec={lag_sec}"
