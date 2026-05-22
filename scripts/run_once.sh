#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
SYMBOL="${1:-BTCUSDT_PERP.A}"
LOOKBACK="${2:-6h}"
python -m coinalyze_receiver.cli run-once --symbol "$SYMBOL" --lookback "$LOOKBACK"
