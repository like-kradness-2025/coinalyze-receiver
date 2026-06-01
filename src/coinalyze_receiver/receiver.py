"""Coinalyze data receiver — fetch and store market data."""

import logging
from datetime import datetime, timedelta
from typing import Any

from coinalyze import CoinalyzeClient, HistoryEndpoint, Interval

from .config import Config
from .storage import Storage, ENDPOINT_TABLE_MAP, normalize_timestamps

logger = logging.getLogger(__name__)

# Coinalyze client → endpoint enum
ENDPOINT_MAP: dict[str, HistoryEndpoint] = {
    "ohlcv": HistoryEndpoint.OHLCV,
    "open-interest": HistoryEndpoint.OI,
    "liquidation": HistoryEndpoint.LIQUIDATION,
    "funding-rate": HistoryEndpoint.FUNDING_RATE,
    "long-short-ratio": HistoryEndpoint.LSRATIO,
}


def _close_client(client) -> None:
    """Close a CoinalyzeClient or its underlying HTTP client if available."""
    close = getattr(client, "close", None)
    if callable(close):
        close()
        return

    inner = getattr(client, "_client", None)
    inner_close = getattr(inner, "close", None)
    if callable(inner_close):
        inner_close()


def _interval_enum(interval_str: str) -> Interval:
    mapping = {
        "1min": Interval.M1,
        "5min": Interval.M5,
        "15min": Interval.M15,
        "30min": Interval.M30,
        "1hour": Interval.H1,
        "2hour": Interval.H2,
        "4hour": Interval.H4,
        "6hour": Interval.H6,
        "12hour": Interval.H12,
        "daily": Interval.D1,
    }
    if interval_str not in mapping:
        raise ValueError(f"Unknown interval: {interval_str}. Valid: {list(mapping.keys())}")
    return mapping[interval_str]


class Receiver:
    """Orchestrates API fetching and storage for configured symbols."""

    def __init__(self, config: Config):
        self.config = config
        self.client: Any = None
        self.storage: Any = None
        try:
            self.client = CoinalyzeClient(api_key=config.api_key)
            self.storage = Storage(config.db_path)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Close the underlying HTTP client."""
        if self.client is not None:
            _close_client(self.client)
            self.client = None

    def fetch_and_store(
        self,
        endpoint: str,
        symbol: str,
        interval: str,
        days_back: int = 7,
    ) -> int:
        """Fetch data for one endpoint/symbol/interval and store it.

        Uses incremental sync: only fetches data not already in DB.
        Returns number of new rows stored.
        """
        table = ENDPOINT_TABLE_MAP[endpoint]
        api_endpoint = ENDPOINT_MAP[endpoint]
        interval_enum = _interval_enum(interval)

        # Determine date range
        end_dt = datetime.utcnow()
        min_ts, max_ts = self.storage.get_existing_range(table, symbol)

        if max_ts is not None:
            # Incremental: fetch from last stored timestamp + 1 interval
            gap = _interval_timedelta(interval_enum)
            start_dt = datetime.utcfromtimestamp(max_ts) + gap
            if start_dt >= end_dt:
                logger.info(
                    "[%s] %s %s: data is current (last=%s)",
                    symbol, endpoint, interval,
                    datetime.utcfromtimestamp(max_ts).isoformat(),
                )
                return 0
        else:
            start_dt = end_dt - timedelta(days=days_back)

        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")

        logger.info(
            "[%s] Fetching %s %s [%s → %s]",
            symbol, endpoint, interval, start_str, end_str,
        )

        df = self.client.get_history_df(
            endpoint=api_endpoint,
            symbols=symbol,
            interval=interval_enum,
            start=start_str,
            end=end_str,
        )

        if df.empty:
            logger.info("[%s] %s %s: no data returned", symbol, endpoint, interval)
            return 0

        # Convert timestamp column to UNIX int
        df = normalize_timestamps(df)

        rows = self.storage.upsert_dataframe(table, df)
        logger.info(
            "[%s] %s %s: stored %d rows (total: %d)",
            symbol, endpoint, interval, rows,
            self.storage.count_rows(table, symbol),
        )
        return rows

    def run_all(self, days_back: int = 7) -> dict[str, int]:
        """Fetch and store all configured endpoints for all symbols."""
        results: dict[str, int] = {}
        endpoints = list(ENDPOINT_MAP.keys())

        for symbol in self.config.symbols:
            for interval in self.config.intervals:
                for ep in endpoints:
                    try:
                        n = self.fetch_and_store(ep, symbol, interval, days_back)
                        results[f"{symbol}/{ep}/{interval}"] = n
                    except Exception as e:
                        logger.error("[%s] %s %s failed: %s", symbol, ep, interval, e)
                        results[f"{symbol}/{ep}/{interval}"] = -1
        return results

    def summary(self, results: dict[str, int]) -> str:
        """Format run summary."""
        lines = ["=== Coinalyze Receiver Summary ==="]
        total_new = 0
        total_err = 0
        for key, n in sorted(results.items()):
            if n < 0:
                lines.append(f"  ❌ {key}: FAILED")
                total_err += 1
            elif n == 0:
                lines.append(f"  ✓ {key}: up-to-date")
            else:
                lines.append(f"  ✓ {key}: {n} new rows")
                total_new += n
        lines.append(f"Total: {total_new} new rows, {total_err} errors")
        return "\n".join(lines)


def _interval_timedelta(interval: Interval) -> timedelta:
    mapping = {
        Interval.M1: timedelta(minutes=1),
        Interval.M5: timedelta(minutes=5),
        Interval.M15: timedelta(minutes=15),
        Interval.M30: timedelta(minutes=30),
        Interval.H1: timedelta(hours=1),
        Interval.H2: timedelta(hours=2),
        Interval.H4: timedelta(hours=4),
        Interval.H6: timedelta(hours=6),
        Interval.H12: timedelta(hours=12),
        Interval.D1: timedelta(days=1),
    }
    return mapping[interval]
