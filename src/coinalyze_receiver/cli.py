"""CLI entry point for coinalyze-receiver."""

import argparse
import logging
import sys

from .config import Config
from .receiver import Receiver
from .selected20 import Selected20Fetcher, load_selected20


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Coinalyze market data receiver — download and store market data locally."
    )
    sub = parser.add_subparsers(dest="command", help="Sub-command")

    # --- default mode ---
    parser.add_argument(
        "--symbols", "-s",
        help="Comma-separated symbols (default: $COINALYZE_SYMBOLS or BTCUSDT_PERP.A)",
    )
    parser.add_argument(
        "--intervals", "-i",
        help="Comma-separated intervals (default: $COINALYZE_INTERVALS or 1hour)",
    )
    parser.add_argument(
        "--days", "-d", type=int, default=7,
        help="Days back to fetch for initial sync (default: 7)",
    )
    parser.add_argument(
        "--db",
        help="SQLite DB path (default: $COINALYZE_DB_PATH or ./data/coinalyze.db)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--list-markets", action="store_true",
        help="List available markets from Coinalyze API and exit",
    )
    parser.add_argument(
        "--list-exchanges", action="store_true",
        help="List available exchanges from Coinalyze API and exit",
    )
    parser.add_argument(
        "--search",
        help="Search markets by keyword (e.g. BTC, ETH)",
    )

    # --- selected20 subcommand ---
    p20 = sub.add_parser("selected20", help="BTC Selected 20 — 1min OHLCV for 21 BTC markets")
    p20.add_argument(
        "--days", "-d", type=int, default=1,
        help="Days back for initial sync (default: 1)",
    )
    p20.add_argument(
        "--db",
        help="SQLite DB path (default: ./data/coinalyze_1min.db)",
    )
    p20.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )
    p20.add_argument(
        "--show", action="store_true",
        help="List the 21 symbols and exit",
    )

    args = parser.parse_args()
    config = Config.from_env()

    if args.verbose:
        config.log_level = "DEBUG"

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # --- selected20 subcommand ---
    if args.command == "selected20":
        if args.db:
            config.db_path = args.db

        if args.show:
            entries = load_selected20()
            print(f"{'Symbol':<25} {'Type':<8} {'Exchange':<12} {'Market':<50}")
            print("-" * 100)
            for e in entries:
                mtype = "perp" if e.get("market_type") == "future" else "spot"
                print(f"{e['symbol']:<25} {mtype:<8} {e['exchange_name']:<12} {e['market_name']:<50}")
            print(f"\nTotal: {len(entries)} symbols")
            return

        fetcher = None
        try:
            fetcher = Selected20Fetcher(config)
            print(f"DB: {fetcher.db_path}")
            print(
                f"Symbols: {len(fetcher.all_symbols)} "
                f"(spot={len(fetcher.spot_symbols)}, perp={len(fetcher.perp_symbols)})"
            )
            print(f"Lookback: {args.days} day(s)")
            print()

            results = fetcher.run_all(days_back=args.days)
            print()
            print(fetcher.summary(results))
        finally:
            if fetcher is not None:
                fetcher.close()
        return

    # --- default mode ---
    if args.symbols:
        config.symbols = [s.strip() for s in args.symbols.split(",")]
    if args.intervals:
        config.intervals = [i.strip() for i in args.intervals.split(",")]
    if args.db:
        config.db_path = args.db

    errors = config.validate()
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    receiver = None
    try:
        active_receiver = Receiver(config)
        receiver = active_receiver

        if args.list_exchanges:
            exchanges = active_receiver.client.get_exchanges()
            print(f"{'Exchange':<25} Code")
            print("-" * 35)
            for e in exchanges:
                print(f"{e['name']:<25} {e['code']}")
            return

        if args.list_markets or args.search:
            markets = active_receiver.client.get_future_markets()
            keyword = args.search.upper() if args.search else None
            matches = []
            for m in markets:
                sym = m.get("symbol", "")
                base = m.get("base_asset", "")
                if keyword and keyword not in sym and keyword not in base:
                    continue
                matches.append(m)
            print(f"{'Symbol':<30} {'Exchange':<10} {'Base':<10} {'Perp':<5} {'OHLCV':<5} {'LS':<5}")
            print("-" * 80)
            for m in matches[:50]:
                print(
                    f"{m['symbol']:<30} {m['exchange']:<10} {m['base_asset']:<10} "
                    f"{'✓' if m.get('is_perpetual') else '':<5} "
                    f"{'✓' if m.get('has_ohlcv_data') else '':<5} "
                    f"{'✓' if m.get('has_long_short_ratio_data') else '':<5}"
                )
            if len(matches) > 50:
                print(f"... and {len(matches) - 50} more (total: {len(matches)})")
            elif not keyword:
                print(f"\nTotal markets: {len(matches)}")
            return

        print(f"DB: {config.db_path}")
        print(f"Symbols: {', '.join(config.symbols)}")
        print(f"Intervals: {', '.join(config.intervals)}")
        print(f"Lookback: {args.days} days")
        print()

        results = receiver.run_all(days_back=args.days)
        print()
        print(receiver.summary(results))
    finally:
        if receiver is not None:
            receiver.close()


if __name__ == "__main__":
    main()
