from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .api import CoinalyzeClient
from .config import load_config
from .notifier import send_discord_notification
from .receiver import CoinalyzeReceiver
from .renderer import filter_footprint_by_ts, render_cvd_heatmap
from .timeutil import parse_duration_seconds
from .transform import build_pseudo_footprint


DEFAULT_PRICE_BUCKET_USD = 10.0
DEFAULT_RENDER_LOOKBACK = "6h"
DEFAULT_RENDER_LAST_BARS = 96


def _print_results(results) -> None:
    for r in results:
        status = "ok" if r.ok else "fail"
        detail = f"raw={r.raw_count} normalized={r.normalized_count}"
        if r.error:
            detail += f" error={r.error}"
        print(f"[{status}] {r.dataset}: {detail}")


def _parse_iso_ts(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())


def _resolve_render_window(args: argparse.Namespace) -> tuple[int | None, int | None]:
    if args.since and args.lookback:
        raise SystemExit("--since と --lookback は同時指定できません")
    if args.last_bars and (args.since or args.lookback):
        raise SystemExit("--last-bars は --since / --lookback と同時指定できません")

    if args.since:
        from_ts = _parse_iso_ts(args.since)
    elif args.lookback:
        from_ts = int(time.time()) - parse_duration_seconds(args.lookback)
    elif args.last_bars:
        from_ts = int(time.time()) - args.last_bars * args.interval_min * 60
    else:
        from_ts = int(time.time()) - parse_duration_seconds(DEFAULT_RENDER_LOOKBACK)

    to_ts = _parse_iso_ts(args.to) if args.to else None
    return from_ts, to_ts


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


def cmd_render(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    ohlcv_path = cfg.output_dir / "normalized" / "ohlcv.jsonl"
    if not ohlcv_path.exists():
        print(f"Data not found: {ohlcv_path}")
        return 1

    rows = []
    with ohlcv_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    from_ts, to_ts = _resolve_render_window(args)
    footprint = build_pseudo_footprint(
        rows,
        interval_min=args.interval_min,
        tick_size=args.price_bucket_usd,
    )
    footprint = filter_footprint_by_ts(footprint, from_ts=from_ts, to_ts=to_ts)

    output_png = cfg.output_dir / "cvd_heatmap.png"
    render_cvd_heatmap(
        footprint,
        output_png,
        symbol=cfg.symbol,
        from_ts=from_ts,
        to_ts=to_ts,
    )
    print(f"Chart saved to {output_png} (bucket: {args.price_bucket_usd})")
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    import os
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")

    if not webhook_url:
        print("DISCORD_WEBHOOK_URL is not set in environment.")
        return 1

    image_path = cfg.output_dir / "cvd_heatmap.png"
    if not image_path.exists():
        print(f"Chart image not found: {image_path}")
        return 1

    success = send_discord_notification(
        webhook_url,
        f"Coinalyze CVD Heatmap for {cfg.symbol}",
        image_path,
    )

    print("Notification sent successfully" if success else "Notification failed")
    return 0 if success else 1


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

    p = sub.add_parser("render", help="Draw CVD heatmap from normalized OHLCV data")
    p.add_argument("--interval-min", type=int, default=15)
    p.add_argument("--price-bucket-usd", type=float, default=DEFAULT_PRICE_BUCKET_USD)
    p.add_argument("--lookback", default=None)
    p.add_argument("--since", default=None)
    p.add_argument("--to", default=None)
    p.add_argument("--last-bars", type=int, default=None)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("notify", help="Send PNG chart to Discord")
    p.set_defaults(func=cmd_notify)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
