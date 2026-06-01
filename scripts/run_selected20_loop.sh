#!/usr/bin/env bash
# run_selected20_loop.sh — coinalyze-receiver selected20 常駐ループ
set -euo pipefail

cd "$(dirname "$0")/.."
LOG_DIR="runtime/logs"
PID_DIR="runtime/pids"
mkdir -p "$LOG_DIR" "$PID_DIR"

LOOP_LOG="$LOG_DIR/selected20_loop.log"
PID_FILE="$PID_DIR/selected20_loop.pid"

echo "$$" > "$PID_FILE"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOOP_LOG"
}

log "=== coinalyze-receiver selected20 loop started (PID: $$) ==="

while true; do
    log "--- fetch start ---"
    python3 -m coinalyze_receiver.cli selected20 2>&1 | tee -a "$LOOP_LOG"
    log "--- fetch end (sleep 55s) ---"
    sleep 55
done
