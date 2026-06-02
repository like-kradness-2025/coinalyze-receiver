"""CLI entry point for coinalyze-receiver v2 with 5 subcommands."""

import argparse
import json
import logging
import signal
import sys
import time
from typing import Optional

from coinalyze_receiver.config import Config
from coinalyze_receiver.client import Client as CoinalyzeClient
from coinalyze_receiver.fetcher import (
    ERROR,
    OK,
    FatalError,
    Fetcher,
    LOOKBACK_DAYS_DEFAULT,
    LOOKBACK_SECONDS_DEFAULT,
    SYMBOL_MAP_PATH,
    load_symbols,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool, default_level: int = logging.INFO) -> None:
    """Configure root logging once.

    Args:
        verbose: If True, set level to DEBUG regardless of *default_level*.
        default_level: Default logging level (used only when *verbose* is
            False).
    """
    level = logging.DEBUG if verbose else default_level
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )


# ---------------------------------------------------------------------------
# Symbol-map path (imported from fetcher: SYMBOL_MAP_PATH)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_fetch(config: Config, verbose: bool, lookback_seconds: int = LOOKBACK_SECONDS_DEFAULT) -> None:
    """Run one fetch cycle and print the summary."""
    setup_logging(verbose, logging.INFO)

    fetcher = None
    try:
        fetcher = Fetcher(config)
        results = fetcher.fetch_cycle(lookback_seconds=lookback_seconds)
        print(fetcher.format_summary(results, fetcher.spot_symbols, fetcher.perp_symbols))

        # Exit 0 if no errors, 1 if any ERROR sentinel
        has_error = any(
            code == ERROR
            for sym_res in results.values()
            for code, _ in sym_res.values()
        )
        sys.exit(1 if has_error else 0)

    except FatalError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if fetcher is not None:
            fetcher.close()


def cmd_loop(config: Config, verbose: bool, lookback_seconds: int = LOOKBACK_SECONDS_DEFAULT) -> None:
    """Run an infinite 3-minute fetch loop with graceful shutdown."""
    setup_logging(verbose, logging.INFO)

    shutdown_flag = [False]

    def handler(signum: int, frame) -> None:
        if not shutdown_flag[0]:
            logger.info(
                "Shutdown requested (signal %d), finishing current request...",
                signum,
            )
            shutdown_flag[0] = True

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    CYCLE_SECONDS = 180

    while not shutdown_flag[0]:
        cycle_start = time.time()
        next_start = cycle_start + CYCLE_SECONDS

        fetcher = None
        try:
            fetcher = Fetcher(config)
            results = fetcher.fetch_cycle(lookback_seconds=lookback_seconds)
            print(fetcher.format_summary(results, fetcher.spot_symbols, fetcher.perp_symbols))
        except FatalError as e:
            print(f"FATAL: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            if fetcher is not None:
                fetcher.close()

        if shutdown_flag[0]:
            break

        elapsed = time.time() - cycle_start
        sleep_time = max(0, next_start - time.time())
        if sleep_time > 0:
            time.sleep(sleep_time)
        else:
            overrun = elapsed - CYCLE_SECONDS
            logger.warning(
                "Cycle overran by %.1fs, starting next immediately",
                overrun,
            )


def cmd_show(config: Config, verbose: bool) -> None:
    """Print the symbol map as a table (does NOT call the API)."""
    setup_logging(verbose, logging.WARNING)

    map_path = SYMBOL_MAP_PATH

    if not map_path.exists():
        print(f"Error: symbol map not found at {map_path}", file=sys.stderr)
        sys.exit(1)

    try:
        # Validate + load in one pass (load_symbols returns symbol lists,
        # but we re-read the raw data for full entry fields)
        load_symbols(str(map_path))

        with open(map_path, encoding="utf-8") as f:
            data = json.load(f)

        # Print header
        print(f"{'Symbol':<20} {'Type':<8} {'Exchange Code':<20} {'Market Name':<40}")
        print("-" * 90)

        for entry in data:
            symbol = entry.get("symbol", "")
            market_type = entry.get("market_type", "")
            exchange_code = entry.get("exchange_code", "")
            market_name = entry.get("market_name", "")

            type_label = "perp" if market_type == "future" else market_type

            print(f"{symbol:<20} {type_label:<8} {exchange_code:<20} {market_name:<40}")

    except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list_markets(config: Config, verbose: bool, keyword: Optional[str]) -> None:
    """Query the Coinalyze API for markets matching *keyword*."""
    setup_logging(verbose, logging.WARNING)

    query = (keyword or "").strip()

    client: Optional[CoinalyzeClient] = None
    try:
        client = CoinalyzeClient(config.api_key)
        results = client.search_markets(query) if query else []

        if not query:
            print("No keyword provided. Use: coinalyze-receiver search <keyword>")
            return
        if not results:
            print("No markets found.")
            return

        # Determine column availability from first result
        has_type = any("type" in m for m in results)
        has_ohlcv = any("has_ohlcv" in m or "has_ohlcv_data" in m for m in results)
        has_ls = any(
            "has_long_short_ratio" in m or "has_long_short_ratio_data" in m
            for m in results
        )

        # Header
        headers = ["Symbol", "Exchange", "Base", "Type"] if has_type else ["Symbol", "Exchange", "Base"]
        if has_ohlcv:
            headers.append("OHLCV")
        if has_ls:
            headers.append("LS")

        print("  ".join(f"{h:<{_col_width(h, len(headers))}}" for h in headers))
        print("-" * 80)

        for m in results:
            symbol = m.get("symbol", "")
            exchange = m.get("exchange_code") or m.get("exchange", "")
            base = m.get("base_asset", "")
            market_type = m.get("type", "")
            type_label = "perp" if market_type == "future" else market_type

            ohlcv_flag = "✓" if (m.get("has_ohlcv") or m.get("has_ohlcv_data")) else ""
            ls_flag = (
                "✓"
                if (m.get("has_long_short_ratio") or m.get("has_long_short_ratio_data"))
                else ""
            )

            cols = [symbol, exchange, base]
            if has_type:
                cols.append(type_label)
            if has_ohlcv:
                cols.append(ohlcv_flag)
            if has_ls:
                cols.append(ls_flag)

            print("  ".join(f"{c:<{_col_width(h, len(headers))}}" for c, h in zip(cols, headers)))

    except Exception as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if client is not None:
            client.close()


def _col_width(header: str, ncols: int) -> int:
    """Return a sensible column width based on header name."""
    widths = {
        "Symbol": 22,
        "Exchange": 14,
        "Base": 14,
        "Type": 10,
        "OHLCV": 6,
        "LS": 6,
    }
    return widths.get(header, max(len(header) + 2, 10))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="coinalyze-receiver v2")
    sub = parser.add_subparsers(dest="command", required=True)

    # fetch
    p_fetch = sub.add_parser("fetch", help="Run one fetch cycle")
    p_fetch.add_argument("-v", "--verbose", action="store_true")
    p_fetch.add_argument("--lookback", "-L", type=int, default=LOOKBACK_DAYS_DEFAULT,
                        help="Days of lookback for empty DB / gap filling (default: %(default)s)")

    # loop
    p_loop = sub.add_parser("loop", help="Run infinite 3-minute fetch loop")
    p_loop.add_argument("-v", "--verbose", action="store_true")
    p_loop.add_argument("--lookback", "-L", type=int, default=LOOKBACK_DAYS_DEFAULT,
                        help="Days of lookback for empty DB / gap filling (default: %(default)s)")

    # show
    p_show = sub.add_parser("show", help="Show symbol map")
    p_show.add_argument("-v", "--verbose", action="store_true")

    # list-markets
    p_lm = sub.add_parser("list-markets", help="List available markets from API")
    p_lm.add_argument("keyword", nargs="?", default=None)
    p_lm.add_argument("-v", "--verbose", action="store_true")

    # search
    p_sr = sub.add_parser("search", help="Search markets (alias for list-markets)")
    p_sr.add_argument("keyword")
    p_sr.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()
    config = Config.from_env()

    # Validate config for commands that need the API key
    if args.command in ("fetch", "loop", "list-markets", "search"):
        errors = config.validate()
        if errors:
            for e in errors:
                print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    # Dispatch
    if args.command == "fetch":
        cmd_fetch(config, args.verbose, lookback_seconds=args.lookback * 86400)
    elif args.command == "loop":
        cmd_loop(config, args.verbose, lookback_seconds=args.lookback * 86400)
    elif args.command == "show":
        cmd_show(config, args.verbose)
    elif args.command == "list-markets":
        cmd_list_markets(config, args.verbose, args.keyword)
    elif args.command == "search":
        cmd_list_markets(config, args.verbose, args.keyword)
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
