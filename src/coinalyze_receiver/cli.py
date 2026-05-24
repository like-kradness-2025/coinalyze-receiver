"""CLI entry point for coinalyze-receiver."""

import argparse
import logging
import sys

from .config import Config
from .receiver import Receiver


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Coinalyze market data receiver — download and store market data locally."
    )
    parser.add_argument(
        "--symbols",
        "-s",
        help="Comma-separated symbols (default: $COINALYZE_SYMBOLS or BTCUSDT_PERP.A)",
    )
    parser.add_argument(
        "--intervals",
        "-i",
        help="Comma-separated intervals (default: $COINALYZE_INTERVALS or 1hour)",
    )
    parser.add_argument(
        "--days",
        "-d",
        type=int,
        default=7,
        help="Days back to fetch for initial sync (default: 7)",
    )
    parser.add_argument(
        "--db",
        help="SQLite DB path (default: $COINALYZE_DB_PATH or ./data/coinalyze.db)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--list-markets",
        action="store_true",
        help="List available markets from Coinalyze API and exit",
    )
    parser.add_argument(
        "--list-exchanges",
        action="store_true",
        help="List available exchanges from Coinalyze API and exit",
    )
    parser.add_argument(
        "--search",
        help="Search markets by keyword (e.g. BTC, ETH)",
    )

    args = parser.parse_args()
    config = Config.from_env()

    if args.symbols:
        config.symbols = [s.strip() for s in args.symbols.split(",")]
    if args.intervals:
        config.intervals = [i.strip() for i in args.intervals.split(",")]
    if args.db:
        config.db_path = args.db
    if args.verbose:
        config.log_level = "DEBUG"

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    receiver = Receiver(config)

    if args.list_exchanges:
        exchanges = receiver.client.get_exchanges()
        print(f"{'Exchange':<25} Code")
        print("-" * 35)
        for e in exchanges:
            print(f"{e['name']:<25} {e['code']}")
        return

    if args.list_markets or args.search:
        markets = receiver.client.get_future_markets()
        keyword = args.search.upper() if args.search else None
        matches = []
        for m in markets:
            sym = m.get("symbol", "")
            ex = m.get("exchange", "")
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

    # Validate config
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"DB: {config.db_path}")
    print(f"Symbols: {', '.join(config.symbols)}")
    print(f"Intervals: {', '.join(config.intervals)}")
    print(f"Lookback: {args.days} days")
    print()

    results = receiver.run_all(days_back=args.days)
    print()
    print(receiver.summary(results))


if __name__ == "__main__":
    main()
