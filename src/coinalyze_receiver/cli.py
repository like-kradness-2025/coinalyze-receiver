from __future__ import annotations

import argparse
import sys
import time
from typing import Sequence

from .api import CoinalyzeClient
from .config import load_config
from .receiver import CoinalyzeReceiver
from .timeutil import parse_duration_seconds


def _print_results(results) -> None:
    for r in results:
        status = "ok" if r.ok else "fail"
        detail = f"raw={r.raw_count} normalized={r.normalized_count}"
        if r.error:
            detail += f" error={r.error}"
        print(f"[{status}] {r.dataset}: {detail}")


def cmd_markets(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    data = CoinalyzeClient(cfg).markets()
    query = (args.query or "").lower()
    count = 0
    for item in data or []:
        text = str(item)
        if query and query not in text.lower():
            continue
        print(text)
        count += 1
    print(f"matched={count}", file=sys.stderr)
    return 0


def cmd_run_once(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    receiver = CoinalyzeReceiver(cfg)
    results = receiver.fetch_once(symbol=args.symbol or cfg.symbol, lookback=args.lookback or cfg.lookback)
    _print_results(results)
    return 0 if all(r.ok for r in results) else 2


def cmd_loop(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    every_sec = parse_duration_seconds(args.every)
    if every_sec <= 0:
        raise SystemExit("--every must be positive")
    receiver = CoinalyzeReceiver(cfg)
    while True:
        started = time.time()
        results = receiver.fetch_once(symbol=args.symbol or cfg.symbol, lookback=args.lookback or cfg.lookback)
        _print_results(results)
        elapsed = time.time() - started
        time.sleep(max(0.0, every_sec - elapsed))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coinalyze-receiver")
    parser.add_argument("--config", default="config/default.json")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("markets", help="List Coinalyze future markets")
    p.add_argument("--query", default="")
    p.set_defaults(func=cmd_markets)

    p = sub.add_parser("run-once", help="Fetch one lookback window and save JSONL")
    p.add_argument("--symbol", default=None)
    p.add_argument("--lookback", default=None)
    p.set_defaults(func=cmd_run_once)

    p = sub.add_parser("loop", help="Fetch repeatedly")
    p.add_argument("--symbol", default=None)
    p.add_argument("--lookback", default=None)
    p.add_argument("--every", default="15m")
    p.set_defaults(func=cmd_loop)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
