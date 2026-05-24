"""BTC Selected 20 fetcher — 1-minute OHLCV for all 20 symbols."""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from coinalyze import CoinalyzeClient, HistoryEndpoint, Interval

from .config import Config
from .storage import Storage, ENDPOINT_TABLE_MAP, normalize_timestamps

logger = logging.getLogger(__name__)

SELECTED20_PATH = Path.home() / ".hermes" / "data" / "coinalyze" / "coinalyze-btc-selected-20-symbol-market-map.json"
DEFAULT_DB_DIR = Path.cwd() / "data"


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

        end_dt = datetime.utcnow()
        start_dt = end_dt - timedelta(days=days_back)

        for sym in symbols:
            try:
                self._rate_limited_call()

                # Incremental: start from last timestamp + 1 minute, or days_back
                min_ts, max_ts = self.storage.get_existing_range("ohlcv_bars", sym)
                if max_ts is not None:
                    inc_start = datetime.utcfromtimestamp(max_ts) + timedelta(minutes=1)
                    if inc_start >= end_dt:
                        logger.info("[%s] ohlcv 1min: up-to-date (last=%s)", sym,
                                    datetime.utcfromtimestamp(max_ts).isoformat())
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

    def run_all(self, days_back: int = 1) -> dict[str, int]:
        """Fetch 1min OHLCV for all 20 symbols."""
        logger.info("=== BTC Selected20 — 1min OHLCV fetch ===")
        logger.info("Symbols: %d (spot=%d, perp=%d)", len(self.all_symbols),
                     len(self.spot_symbols), len(self.perp_symbols))
        return self.fetch_ohlcv_1min(self.all_symbols, days_back)

    def summary(self, results: dict[str, int]) -> str:
        """Format run summary."""
        lines = ["=== BTC Selected20 Summary ==="]
        total_new = 0
        total_err = 0
        for sym, n in sorted(results.items()):
            if n < 0:
                lines.append(f"  ❌ {sym}: FAILED")
                total_err += 1
            elif n == 0:
                lines.append(f"  ✓ {sym}: up-to-date")
            else:
                lines.append(f"  ✓ {sym}: {n} new rows")
                total_new += n

        # Per-type totals
        spot_hits = sum(results.get(s, 0) for s in self.spot_symbols if results.get(s, 0) > 0)
        perp_hits = sum(results.get(s, 0) for s in self.perp_symbols if results.get(s, 0) > 0)

        lines.append(f"")
        lines.append(f"Total: {total_new} new rows, {total_err} errors")
        lines.append(f"  Spots: {spot_hits} rows")
        lines.append(f"  Perps: {perp_hits} rows")
        lines.append(f"DB: {self.db_path}")
        return "\n".join(lines)
