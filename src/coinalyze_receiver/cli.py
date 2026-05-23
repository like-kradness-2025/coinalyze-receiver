from __future__ import annotations

import argparse
import sys
import time
from typing import Sequence
from pathlib import Path

from .api import CoinalyzeClient
from .config import load_config
from .receiver import CoinalyzeReceiver
from .timeutil import parse_duration_seconds
from .transform import build_pseudo_footprint
from .renderer import render_cvd_heatmap
from .notifier import send_discord_notification


DEFAULT_PRICE_BUCKET_USD = 10.0


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


def cmd_render(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    ohlcv_path = cfg.output_dir / "normalized" / "ohlcv.jsonl"
    if not ohlcv_path.exists():
        print(f"Data not found: {ohlcv_path}")
        return 1
    
    import json
    rows = []
    with ohlcv_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    
    # Pseudo Footprint への変換
    footprint = build_pseudo_footprint(
        rows, 
        interval_min=args.interval_min, 
        tick_size=args.price_bucket_usd
    )
    
    output_png = cfg.output_dir / "cvd_heatmap.png"
    render_cvd_heatmap(
        footprint, 
        output_png, 
        symbol=cfg.symbol,
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
