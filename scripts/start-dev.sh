#!/bin/sh
# Start Pilot once per container and fail loudly when it exits during startup.
set -eu

BENCH_NAME="${BENCH_NAME:-development-bench}"
PILOT_DIR="${PILOT_DIR:-/workspace/pilot}"
PID_FILE="/tmp/pilot-${BENCH_NAME}.pid"
LOG_FILE="/tmp/pilot-${BENCH_NAME}.log"
PILOT_BIN="${PILOT_DIR}/bin/pilot"

if [ ! -x "$PILOT_BIN" ]; then
	printf 'Pilot is not installed at %s; run python installer.py first.\n' "$PILOT_BIN" >&2
	exit 1
fi

if [ -s "$PID_FILE" ]; then
	pid="$(sed -n '1p' "$PID_FILE")"
	case "$pid" in
		*[!0-9]*|'') pid='' ;;
	esac
	if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
		printf 'Pilot bench %s is already running as PID %s.\n' "$BENCH_NAME" "$pid"
		exit 0
	fi
fi

nohup "$PILOT_BIN" -b "$BENCH_NAME" start >"$LOG_FILE" 2>&1 </dev/null &
pid=$!
printf '%s\n' "$pid" >"$PID_FILE"

# Catch immediate configuration/startup failures while keeping postStart quick.
sleep 2
if ! kill -0 "$pid" 2>/dev/null; then
	printf 'Pilot failed to start. Recent output from %s:\n' "$LOG_FILE" >&2
	tail -n 40 "$LOG_FILE" >&2 || true
	exit 1
fi

printf 'Pilot bench %s started as PID %s (log: %s).\n' "$BENCH_NAME" "$pid" "$LOG_FILE"
