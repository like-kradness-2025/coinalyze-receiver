"""Fetcher — orchestrate incremental sync of Coinalyze market data."""

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from coinalyze_receiver.client import Client as CoinalyzeClient
from coinalyze_receiver.config import Config
from coinalyze_receiver.storage import Storage, normalize_timestamps

logger = logging.getLogger(__name__)

# Default path for the symbol market map JSON
SYMBOL_MAP_PATH = (
    Path.home()
    / ".hermes"
    / "data"
    / "coinalyze"
    / "coinalyze-btc-selected-20-symbol-market-map.json"
)

class FatalError(Exception):
    """Fatal error that should abort the current cycle immediately."""
    pass


# ---------------------------------------------------------------------------
# Sentinel result codes
# ---------------------------------------------------------------------------
OK = 0       # success (including up-to-date, meaning 0 new rows)
ERROR = -1   # API / network failure
NODATA = -2  # empty response from API

# ---------------------------------------------------------------------------
# Endpoint configuration: (endpoint_name, interval, table_name)
# ---------------------------------------------------------------------------
ENDPOINT_CONFIGS: list[tuple[str, str, str]] = [
    ("ohlcv", "1min", "ohlcv_bars"),                # all symbols
    ("open-interest", "1min", "open_interest"),      # perp only
    ("funding-rate", "1min", "funding_rates"),        # perp only
    ("liquidation", "1min", "liquidations"),          # perp only
    ("long-short-ratio", "15min", "ls_ratios"),       # perp only
]

# Endpoints that only apply to perpetual / futures symbols
_PERP_ONLY_ENDPOINTS = {"open-interest", "funding-rate", "liquidation", "long-short-ratio"}

# ---------------------------------------------------------------------------
# Lookback / backfill defaults
# ---------------------------------------------------------------------------
LOOKBACK_DAYS_DEFAULT = 7
LOOKBACK_SECONDS_DEFAULT = LOOKBACK_DAYS_DEFAULT * 86400

# ---------------------------------------------------------------------------
# Response field → DataFrame column mapping per endpoint
# ---------------------------------------------------------------------------
_FIELD_MAPS: dict[str, dict[str, str]] = {
    "ohlcv": {
        "t": "timestamp",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
        "bv": "buyvolume",
        "tx": "trades",
        "btx": "buytrades",
    },
    "open-interest": {
        "t": "timestamp",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
    },
    "funding-rate": {
        "t": "timestamp",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
    },
    "liquidation": {
        "t": "timestamp",
        "l": "longvolume",
        "s": "shortvolume",
    },
    "long-short-ratio": {
        "t": "timestamp",
        "r": "ratio",
        "lp": "longpct",
        "sp": "shortpct",
    },
}

# ---------------------------------------------------------------------------
# Symbol-map loading  (used by Fetcher.__init__ and independently testable)
# ---------------------------------------------------------------------------

def load_symbols(symbol_map_path: str) -> tuple[list[str], list[str], list[str]]:
    """Load and validate the symbol market-map JSON file.

    Returns:
        (spot_symbols, perp_symbols, all_symbols)  — each a list of symbol
        strings ordered by their appearance in the file.
    """
    with open(symbol_map_path, encoding="utf-8") as f:
        data = json.load(f)

    # Must be a list
    if not isinstance(data, list):
        raise ValueError(
            f"Symbol map must be a JSON array, got {type(data).__name__}"
        )

    # Must have exactly 21 entries
    if len(data) != 21:
        raise ValueError(
            f"Symbol map must have exactly 21 entries, got {len(data)}"
        )

    seen = set()
    spot_symbols: list[str] = []
    perp_symbols: list[str] = []
    all_symbols: list[str] = []

    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError(
                f"Each entry must be an object, got {type(entry).__name__}"
            )

        symbol = entry.get("symbol")
        market_type = entry.get("market_type")

        if not symbol or not isinstance(symbol, str):
            raise ValueError(f"Entry missing valid 'symbol': {entry}")
        if market_type not in ("spot", "future"):
            raise ValueError(
                f"Entry '{symbol}' has invalid market_type '{market_type}'"
            )

        # Duplicate check
        if symbol in seen:
            raise ValueError(f"Duplicate symbol in market map: {symbol}")
        seen.add(symbol)

        all_symbols.append(symbol)
        if market_type == "spot":
            spot_symbols.append(symbol)
        else:
            perp_symbols.append(symbol)

    # Both categories must be non-empty
    if not spot_symbols:
        raise ValueError("Symbol map contains no spot markets")
    if not perp_symbols:
        raise ValueError("Symbol map contains no perpetual markets")

    return spot_symbols, perp_symbols, all_symbols


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class Fetcher:
    """Orchestrate incremental data fetching for all configured symbols."""

    def __init__(self, config: Config) -> None:
        # Initialise to safe sentinels so close() can run on failure
        self.client = None  # type: ignore[assignment]
        self.storage = None  # type: ignore[assignment]
        self.spot_symbols: list[str] = []
        self.perp_symbols: list[str] = []
        self.all_symbols: list[str] = []

        # Symbol-map path (shared module-level constant)
        map_path = SYMBOL_MAP_PATH

        try:
            spot, perp, all_syms = load_symbols(str(map_path))
            self.spot_symbols = spot
            self.perp_symbols = perp
            self.all_symbols = all_syms

            self.client = CoinalyzeClient(config.api_key)  # type: ignore[assignment]
            self.storage = Storage(config.db_path)  # type: ignore[assignment]
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        """Release the HTTP client connection."""
        if self.client is not None:
            self.client.close()
            self.client = None

    # ------------------------------------------------------------------
    # Timestamp helpers
    # ------------------------------------------------------------------

    @staticmethod
    def build_timestamps() -> tuple[int, int]:
        """Return (common_from, to) as minute-aligned UNIX seconds.

        ``common_from`` is the start of the *look-back window* (180 seconds
        in the past, floored to the minute).  ``to`` is the current minute
        boundary.
        """
        now = int(time.time())
        to = (now // 60) * 60
        common_from = ((now - 180) // 60) * 60
        return common_from, to

    # ------------------------------------------------------------------
    # Single fetch
    # ------------------------------------------------------------------

    def _fetch_range(
        self,
        endpoint: str,
        symbol: str,
        fetch_from: int,
        fetch_to: int,
        interval: str,
        table: str,
    ) -> tuple[int, str]:
        """Fetch a specific time range and store it.

        Returns:
            ``(result_code, detail_string)`` — see :meth:`fetch_one`.
        """
        assert self.storage is not None, "Fetcher not properly initialised"
        assert self.client is not None, "Fetcher not properly initialised"

        if fetch_from >= fetch_to:
            return (OK, "up-to-date")

        # -- Make the API call ---------------------------------------------
        try:
            response = self.client.get_history(
                endpoint, symbol, fetch_from, fetch_to, interval
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            reason = exc.response.reason_phrase or "HTTP Error"
            msg = f"{status} {reason}"
            if status == 401:
                raise FatalError(f"Authentication failed (401): check COINALYZE_API_KEY") from exc
            logger.error("HTTP %s for %s/%s: %s", status, symbol, endpoint, msg)
            return (ERROR, msg)
        except httpx.RequestError as exc:
            msg = f"Network error: {exc}"
            logger.error("Request failed for %s/%s: %s", symbol, endpoint, msg)
            return (ERROR, msg)
        except Exception as exc:
            msg = f"Unexpected error: {exc}"
            logger.error("Unexpected error for %s/%s: %s", symbol, endpoint, msg)
            return (ERROR, msg)

        # -- Empty response -------------------------------------------------
        if not response or not isinstance(response, list) or len(response) == 0:
            logger.debug("No data for %s/%s (%d – %d)", symbol, endpoint, fetch_from, fetch_to)
            return (NODATA, "no data")

        # -- Map response to DataFrame --------------------------------------
        # Response format: [{"symbol": "X", "history": [{"t": ..., ...}, ...]}, ...]
        field_map = _FIELD_MAPS.get(endpoint, {})
        rows: list[dict[str, Any]] = []
        for entry in response:
            if not isinstance(entry, dict):
                continue
            # Each entry has symbol + history array with bar data
            bar_list = entry.get("history", [])
            if not isinstance(bar_list, list) or not bar_list:
                continue
            for bar in bar_list:
                if not isinstance(bar, dict):
                    continue
                row: dict[str, Any] = {"symbol": symbol}
                for api_key, col_name in field_map.items():
                    if api_key in bar:
                        row[col_name] = bar[api_key]
                rows.append(row)

        if not rows:
            return (NODATA, "no data")

        # Determine column order: symbol first, then the mapped columns in
        # field-map order, but only those that actually appear in the data.
        available_cols = set(rows[0].keys())
        ordered_cols = ["symbol"] + [
            c for c in field_map.values()
            if c in available_cols and c != "symbol"
        ]

        df = pd.DataFrame(rows, columns=ordered_cols)
        df = normalize_timestamps(df)

        # -- Store ----------------------------------------------------------
        before = self.storage.count_rows(table, symbol)
        self.storage.upsert_dataframe(table, df)
        after = self.storage.count_rows(table, symbol)
        inserted = after - before

        return (inserted, f"{inserted} new rows")

    def fetch_one(
        self,
        endpoint: str,
        symbol: str,
        from_ts: int,
        to_ts: int,
        interval: str,
        table: str,
        lookback_seconds: int = 0,
    ) -> tuple[int, str]:
        """Fetch one symbol/endpoint pair and store results.

        When *lookback_seconds* is > 0 the method will also perform a
        one-time backfill / gap-fill if the database is empty or has a
        gap before the earliest stored timestamp.

        Returns:
            ``(result_code, detail_string)`` where *result_code* is one of
            ``OK`` (>=0, actual number of new rows stored), ``ERROR`` (-1),
            or ``NODATA`` (-2).  The detail string is a human-readable
            description.
        """
        assert self.storage is not None, "Fetcher not properly initialised"

        min_ts, max_ts = self.storage.get_existing_range(table, symbol)
        total_inserted = 0

        # ------------------------------------------------------------------
        # Phase 1 — Backfill / gap filling
        # ------------------------------------------------------------------
        if lookback_seconds > 0 and min_ts is not None:
            backfill_target = to_ts - lookback_seconds
            if min_ts > backfill_target:
                backfill_from = backfill_target
                backfill_to = min_ts - 60
                if backfill_from < backfill_to:
                    logger.info(
                        "Backfill %s/%s: [%s → %s] (%ds window)",
                        symbol, endpoint, backfill_from, backfill_to,
                        lookback_seconds,
                    )
                    code, detail = self._fetch_range(
                        endpoint, symbol, backfill_from, backfill_to,
                        interval, table,
                    )
                    if code < 0:
                        return (code, detail)
                    total_inserted += code

        # ------------------------------------------------------------------
        # Determine fetch start for the main (incremental) fetch
        # ------------------------------------------------------------------
        if lookback_seconds > 0 and min_ts is None:
            # Empty DB — use lookback window (no from_ts clamp)
            fetch_from = to_ts - lookback_seconds
        elif max_ts is not None:
            # Normal incremental
            fetch_from = max(from_ts, max_ts + 60)
        else:
            fetch_from = from_ts

        if fetch_from >= to_ts:
            if total_inserted > 0:
                return (total_inserted, f"{total_inserted} new rows")
            return (OK, "up-to-date")

        # ------------------------------------------------------------------
        # Phase 2 — Main (incremental) fetch
        # ------------------------------------------------------------------
        code, detail = self._fetch_range(
            endpoint, symbol, fetch_from, to_ts, interval, table,
        )
        if code < 0:
            return (code, detail)
        total_inserted += code
        return (total_inserted, f"{total_inserted} new rows")

    # ------------------------------------------------------------------
    # Full cycle
    # ------------------------------------------------------------------

    def fetch_cycle(self, lookback_seconds: int = LOOKBACK_SECONDS_DEFAULT) -> dict[str, dict[str, tuple[int, str]]]:
        """Run one complete fetch cycle over all symbols × data types.

        Returns:
            ``{symbol: {endpoint_name: (result_code, detail_string)}}``

        Raises:
            FatalError if the API returns 401 (authentication failure).
        """
        common_from, to = self.build_timestamps()
        logger.info(
            "Fetch cycle starting: from=%d to=%d (window=%ds)",
            common_from, to, to - common_from,
        )

        results: dict[str, dict[str, tuple[int, str]]] = {}

        for endpoint, interval, table in ENDPOINT_CONFIGS:
            # Determine which symbols apply
            if endpoint in _PERP_ONLY_ENDPOINTS:
                symbols = self.perp_symbols
            else:
                symbols = self.all_symbols

            for symbol in symbols:
                code, detail = self.fetch_one(
                    endpoint, symbol, common_from, to, interval, table,
                    lookback_seconds=lookback_seconds,
                )
                results.setdefault(symbol, {})[endpoint] = (code, detail)

        return results

    # ------------------------------------------------------------------
    # Summary formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_summary(
        results: dict[str, dict[str, tuple[int, str]]],
        spot_symbols: list[str],
        perp_symbols: list[str],
    ) -> str:
        """Format a human-readable cycle summary string.

        Returns a multi-line string with per-symbol results, per-type
        totals, and a symbol-status list.
        """
        if not results:
            return "No results."

        # Collect all endpoint names present in results
        all_endpoints: set[str] = set()
        for sym_results in results.values():
            all_endpoints.update(sym_results.keys())
        endpoint_order = [ec[0] for ec in ENDPOINT_CONFIGS if ec[0] in all_endpoints]

        # -- Per-symbol detail lines ----------------------------------------
        lines: list[str] = []
        # Use JSON map order (perp first, then spot) to match fetch order
        all_symbols = perp_symbols + spot_symbols

        for sym in all_symbols:
            sym_res = results.get(sym, {})
            if not sym_res:
                continue

            parts: list[str] = []

            for ep in endpoint_order:
                if ep not in sym_res:
                    continue
                code, detail = sym_res[ep]
                if code == ERROR:
                    parts.append(f"❌ {ep} ({detail})")
                elif code == NODATA:
                    parts.append(f"◦ {ep} (no data)")
                else:
                    parts.append(f"✓ {ep} ({detail})")

            # Single line — the per-endpoint markers (❌/◦/✓) already carry
            # the severity information; no need for a separate line prefix.
            lines.append(f"{sym}:  " + "  ".join(parts))

        lines.append("")

        # -- Per-type totals ------------------------------------------------
        lines.append("Per-type totals:")
        max_ep_len = max((len(ep) for ep in endpoint_order), default=0)
        for ep in endpoint_order:
            total_new = 0
            no_data_count = 0
            error_count = 0
            for sym_res in results.values():
                if ep in sym_res:
                    code, _ = sym_res[ep]
                    if code > 0:
                        total_new += code
                    elif code == NODATA:
                        no_data_count += 1
                    elif code == ERROR:
                        error_count += 1

            parts = []
            parts.append(f"{total_new:>8} new rows")
            if no_data_count:
                parts.append(f"◦ {no_data_count} no-data")
            if error_count:
                parts.append(f"❌ {error_count} errors")

            status = "✅"
            if error_count:
                status = "❌"
            elif no_data_count and total_new == 0:
                status = "◦"

            lines.append(
                f"  {ep:<{max_ep_len}} :  {'  '.join(parts)}  {status}"
            )

        lines.append("")

        # -- Per-symbol status ----------------------------------------------
        lines.append("Per-symbol:")
        for sym in all_symbols:
            sym_res = results.get(sym, {})
            if not sym_res:
                continue
            has_error = any(code == ERROR for code, _ in sym_res.values())
            all_nodata = all(code == NODATA for code, _ in sym_res.values())

            if has_error:
                lines.append(f"  ❌ {sym}")
            elif all_nodata:
                lines.append(f"  ◦ {sym}")
            else:
                lines.append(f"  ✓ {sym}")

        return "\n".join(lines)
