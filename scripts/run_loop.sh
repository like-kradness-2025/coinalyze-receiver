#!/usr/bin/env bash
# coinalyze-receiver v2 perpetual loop wrapper (nohup)
# Termux: use shebang #!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."

mkdir -p runtime/logs runtime/pids
PID_FILE="runtime/pids/v2.pid"
LOG_FILE="runtime/logs/v2.log"

echo $$ > "$PID_FILE"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

trap 'log "Signal received, stopping..."; kill 0; exit 0' TERM INT

log "=== coinalyze-receiver v2 loop started (PID: $$) ==="

while true; do
    log "--- cycle start ---"
    python3 -m coinalyze_receiver.cli fetch 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=${PIPESTATUS[0]}
    if [ "$EXIT_CODE" -eq 0 ]; then
        log "--- cycle OK ---"
    else
        log "--- cycle ended with errors (exit $EXIT_CODE) ---"
    fi
    sleep 180
done
