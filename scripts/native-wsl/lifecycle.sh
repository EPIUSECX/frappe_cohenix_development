#!/usr/bin/env bash
# Start / stop / restart / status for the Cohenix Pilot bench inside WSL.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

export PATH="$HOME/.local/bin:$PILOT_DIR/bin:$PATH"
PILOT="$(pilot_bin)"
validate_ident "bench" "$BENCH_NAME"
ACTION="${1:-status}"
PID_FILE="$STATE_DIR/pilot-start.pid"
LOG_RUN="$STATE_DIR/pilot-start.log"

case "$ACTION" in
  start)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      log INFO "Pilot already running (pid $(cat "$PID_FILE"))"
      exit 0
    fi
    log INFO "Starting pilot -b $BENCH_NAME (background)"
    # Development start is foreground; keep it alive under nohup for the desktop app.
    nohup "$PILOT" --bench "$BENCH_NAME" start >>"$LOG_RUN" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 2
    if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      die "Pilot failed to stay up; see $LOG_RUN"
    fi
    log INFO "Started pid $(cat "$PID_FILE")"
    ;;
  stop)
    log INFO "Stopping pilot -b $BENCH_NAME"
    "$PILOT" --bench "$BENCH_NAME" stop || true
    if [[ -f "$PID_FILE" ]]; then
      kill "$(cat "$PID_FILE")" 2>/dev/null || true
      rm -f "$PID_FILE"
    fi
    ;;
  restart)
    "$0" stop || true
    sleep 1
    "$0" start
    ;;
  status)
    running=false
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      running=true
    fi
    http_ok=false
    curl -fsS --max-time 2 "http://127.0.0.1:${HTTP_PORT}/api/method/frappe.ping" >/dev/null 2>&1 && http_ok=true || true
    admin_ok=false
    curl -fsS --max-time 2 "http://127.0.0.1:${ADMIN_PORT}/health" >/dev/null 2>&1 && admin_ok=true || true
    printf '{"bench":"%s","process":%s,"frappe_http":%s,"admin_health":%s}\n' \
      "$BENCH_NAME" "$running" "$http_ok" "$admin_ok"
    ;;
  keepalive)
    # Touch a file so the desktop can detect an intentional keep-alive session.
    while true; do
      date -u +"%Y-%m-%dT%H:%M:%SZ" > "$STATE_DIR/keepalive"
      sleep 30
    done
    ;;
  *)
    die "Usage: $0 {start|stop|restart|status|keepalive}"
    ;;
esac
