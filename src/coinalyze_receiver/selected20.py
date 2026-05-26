"""BTC Selected 20 fetcher — 1-minute data for all 20 symbols."""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from coinalyze import CoinalyzeClient, HistoryEndpoint, Interval

from .config import Config
from .storage import Storage, ENDPOINT_TABLE_MAP, normalize_timestamps

logger = logging.getLogger(__name__)

SELECTED20_PATH = Path.home() / ".hermes" / "data" / "coinalyze" / "coinalyze-btc-selected-20-symbol-market-map.json"
DEFAULT_DB_DIR = Path.cwd() / "data"

# All data types to fetch (ohlcv is handled separately)
# Each entry: (endpoint_name, api_endpoint, table_name, interval)
ADDITIONAL_ENDPOINTS: list[tuple[str, HistoryEndpoint, str, Interval]] = [
    ("open-interest", HistoryEndpoint.OI, "open_interest", Interval.M1),
    ("liquidation", HistoryEndpoint.LIQUIDATION, "liquidations", Interval.M1),
    ("funding-rate", HistoryEndpoint.FUNDING_RATE, "funding_rates", Interval.M1),
    # LS ratio not available at 1min; use 15min (smallest available)
    ("long-short-ratio", HistoryEndpoint.LSRATIO, "ls_ratios", Interval.M15),
]


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


def load_selected20(path: Optional[str] = None) -> list[dict]:
    """Load the BTC Selected 20 symbol list from JSON."""
    p = Path(path) if path else SELECTED20_PATH
    if not p.exists():
        raise FileNotFoundError(f"Selected20 file not found: {p}")
    with open(p) as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Selected20 JSON must be a list: {p}")

    required_keys = {"symbol", "market_type"}
    symbols: list[str] = []
    has_spot = False
    has_perp = False
    for idx, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(f"Selected20 entry #{idx} must be an object: {p}")
        missing = required_keys - set(entry)
        if missing:
            raise ValueError(f"Selected20 entry #{idx} missing keys {sorted(missing)}: {p}")
        symbols.append(entry["symbol"])
        mt = entry["market_type"]
        if mt not in ("spot", "future"):
            raise ValueError(f"Selected20 entry #{idx} invalid market_type={mt!r}: {p}")
        if mt == "future":
            has_perp = True
        else:
            has_spot = True

    if len(data) != 20:
        raise ValueError(f"Selected20 must contain exactly 20 entries: {len(data)} in {p}")
    if len(set(symbols)) != len(symbols):
        raise ValueError(f"Selected20 contains duplicate symbols: {p}")
    if not has_spot or not has_perp:
        raise ValueError(f"Selected20 must include both spot and perp symbols: {p}")

    logger.info("Loaded %d symbols from %s", len(data), p)
    return data


def categorize_symbols(entries: list[dict]) -> tuple[list[str], list[str]]:
    """Return (spot_symbols, perp_symbols) based on market_type."""
    spots, perps = [], []
    for e in entries:
        sym = e["symbol"]
        if e.get("market_type") == "future":
            perps.append(sym)
        else:
            spots.append(sym)
    return spots, perps


class Selected20Fetcher:
    """Fetches 1-minute OHLCV data for all BTC Selected 20 symbols."""

    def __init__(self, config: Config, db_name: str = "coinalyze_1min.db"):
        self.config = config
        self.client = CoinalyzeClient(api_key=config.api_key)

        db_path = (config.db_path or "").strip()
        db_dir = Path(db_path).parent if db_path else DEFAULT_DB_DIR
        db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(db_dir / db_name)
        self.storage = Storage(self.db_path)

        # Load symbol list
        self.entries = load_selected20()
        self.spot_symbols, self.perp_symbols = categorize_symbols(self.entries)
        self.all_symbols = self.spot_symbols + self.perp_symbols

        # Rate limiting: 40 calls/min → ~1.5s between calls
        self._call_interval = 2.0  # seconds between API calls
        self._last_call_time = 0.0

    def _rate_limited_call(self):
        """Ensure we don't exceed 40 calls/minute."""
        elapsed = time.time() - self._last_call_time
        if elapsed < self._call_interval:
            time.sleep(self._call_interval - elapsed)
        self._last_call_time = time.time()

    def fetch_ohlcv_1min(
        self, symbols: list[str], days_back: int = 1
    ) -> dict[str, int]:
        """Fetch 1min OHLCV for a list of symbols. Returns {symbol: rows_upserted}."""
        results = {}

        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=days_back)

        for sym in symbols:
            try:
                self._rate_limited_call()

                # Incremental: start from last timestamp + 1 minute, or days_back
                min_ts, max_ts = self.storage.get_existing_range("ohlcv_bars", sym)
                if max_ts is not None:
                    inc_start = datetime.fromtimestamp(max_ts, tz=timezone.utc) + timedelta(minutes=1)
                    if inc_start >= end_dt:
                        logger.info("[%s] ohlcv 1min: up-to-date (last=%s)", sym,
                                    datetime.fromtimestamp(max_ts, tz=timezone.utc).isoformat())
                        results[sym] = 0
                        continue
                    fetch_start = inc_start
                else:
                    fetch_start = start_dt

                logger.info("[%s] Fetching ohlcv 1min [%s → %s]", sym,
                            fetch_start.isoformat(), end_dt.isoformat())

                df = self.client.get_history_df(
                    endpoint=HistoryEndpoint.OHLCV,
                    symbols=sym,
                    interval=Interval.M1,
                    start=fetch_start,
                    end=end_dt,
                )

                if df.empty:
                    logger.info("[%s] ohlcv 1min: no data", sym)
                    results[sym] = 0
                    continue

                # Normalize timestamps to UNIX int
                df = normalize_timestamps(df)

                before_count = self.storage.count_rows("ohlcv_bars", sym)
                rows = self.storage.upsert_dataframe("ohlcv_bars", df)
                after_count = self.storage.count_rows("ohlcv_bars", sym)
                inserted = max(after_count - before_count, 0)
                logger.info(
                    "[%s] ohlcv 1min: fetched %d rows, upserted %d rows, inserted %d rows (total: %d)",
                    sym,
                    len(df),
                    rows,
                    inserted,
                    after_count,
                )
                results[sym] = inserted

            except Exception as e:
                logger.error("[%s] ohlcv 1min failed: %s", sym, e)
                results[sym] = -1

        return results

    def fetch_all_types(
        self, symbols: list[str], days_back: int = 1
    ) -> dict[str, int]:
        """Fetch all additional data types (OI, liquidations, funding, LS ratio)
        for the given symbols at their respective intervals.
        Returns {key: rows_upserted}."""
        results: dict[str, int] = {}
        end_dt = datetime.now(timezone.utc)

        for sym in symbols:
            for ep_name, api_endpoint, table, interval_enum in ADDITIONAL_ENDPOINTS:
                key = f"{sym}/{ep_name}"
                try:
                    self._rate_limited_call()

                    min_ts, max_ts = self.storage.get_existing_range(table, sym)
                    if max_ts is not None:
                        gap = _interval_timedelta(interval_enum)
                        start_dt = datetime.fromtimestamp(max_ts, tz=timezone.utc) + gap
                        if start_dt >= end_dt:
                            logger.info("[%s] %s %s: up-to-date", sym, ep_name, interval_enum.value)
                            continue
                    else:
                        start_dt = end_dt - timedelta(days=days_back)

                    logger.info("[%s] Fetching %s %s [%s → %s]", sym, ep_name, interval_enum.value,
                                start_dt.isoformat(), end_dt.isoformat())

                    df = self.client.get_history_df(
                        endpoint=api_endpoint,
                        symbols=sym,
                        interval=interval_enum,
                        start=start_dt,
                        end=end_dt,
                    )

                    if df.empty:
                        logger.info("[%s] %s 1min: no data", sym, ep_name)
                        continue

                    df = normalize_timestamps(df)
                    before = self.storage.count_rows(table, sym)
                    rows = self.storage.upsert_dataframe(table, df)
                    after = self.storage.count_rows(table, sym)
                    inserted = max(after - before, 0)
                    results[key] = inserted
                    logger.info("[%s] %s %s: %d rows, %d inserted (total: %d)",
                                sym, ep_name, interval_enum.value, len(df), inserted, after)

                except Exception as e:
                    logger.error("[%s] %s %s failed: %s", sym, ep_name, interval_enum.value, e)
                    results[key] = -1

        return results

    def run_all(self, days_back: int = 1) -> dict[str, int]:
        """Fetch 1min OHLCV + all additional data types for all 20 symbols."""
        logger.info("=== BTC Selected20 — Full data fetch (ohlcv + oi + liq + funding + ls) ===")
        logger.info("Symbols: %d (spot=%d, perp=%d)", len(self.all_symbols),
                     len(self.spot_symbols), len(self.perp_symbols))

        results: dict[str, int] = {}

        # 1. OHLCV (existing)
        ohlcv_results = self.fetch_ohlcv_1min(self.all_symbols, days_back)
        for k, v in ohlcv_results.items():
            results[f"{k}/ohlcv"] = v

        # 2. Additional data types
        additional = self.fetch_all_types(self.all_symbols, days_back)
        results.update(additional)

        return results

    def summary(self, results: dict[str, int]) -> str:
        """Format run summary grouped by data type."""
        lines = ["=== BTC Selected20 Summary ==="]

        data_types = ["ohlcv", "open-interest", "liquidation", "funding-rate", "long-short-ratio"]
        totals: dict[str, int] = {dt: 0 for dt in data_types}
        errors: dict[str, int] = {dt: 0 for dt in data_types}

        for key, n in sorted(results.items()):
            # key format: "symbol/ep_name" or "ohlcv:symbol" (legacy)
            parts = key.rsplit("/", 1)
            sym = parts[0]
            ep = parts[1] if len(parts) > 1 else "ohlcv"

            if ep not in totals:
                ep = "ohlcv"  # fallback

            if n < 0:
                lines.append(f"  ❌ {key}")
                errors[ep] += 1
            elif n == 0:
                pass  # up-to-date, skip for brevity
            else:
                lines.append(f"  ✓ {key}: {n} new rows")
                totals[ep] += n

        lines.append("")
        lines.append("--- Totals by type ---")
        for dt in data_types:
            label = dt.replace("-", "_")
            t = totals[dt]
            e = errors[dt]
            status = "✅" if e == 0 else f"⚠️ {e} errors"
            lines.append(f"  {label:20s}: {t:>8d} new rows  {status}")

        # Per-type symbol counts
        line_parts: list[str] = []
        for sym in self.all_symbols:
            sym_ok = sum(1 for k, v in results.items() if k.startswith(sym + "/") and v >= 0)
            sym_total = sum(1 for k in results.keys() if k.startswith(sym + "/"))
            if sym_ok == sym_total:
                line_parts.append(f"  ✓ {sym}")
            else:
                line_parts.append(f"  ⚠️ {sym} ({sym_ok}/{sym_total} OK)")

        lines.append("")
        lines.append("--- Per-symbol ---")
        lines.extend(line_parts)

        lines.append("")
        lines.append(f"DB: {self.db_path}")
        return "\n".join(lines)
