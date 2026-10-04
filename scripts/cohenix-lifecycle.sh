# Shared helpers for Dev Container onCreate / postCreate / postStart.
# Sourced, not executed. POSIX sh. No prompts.

cohenix_truthy() {
	case "${1:-}" in
	1 | true | TRUE | yes | YES | on | ON) return 0 ;;
	*) return 1 ;;
	esac
}

cohenix_log() {
	printf '%s\n' "$*"
}

cohenix_run_devctl() {
	if command -v devctl >/dev/null 2>&1; then
		devctl "$@"
		return
	fi
	PYTHONPATH="${PYTHONPATH:-/workspace}" python3 -m cohenix_dev "$@"
}

cohenix_wait_for_mariadb() {
	if command -v getent >/dev/null 2>&1 && ! getent hosts mariadb >/dev/null 2>&1; then
		cohenix_log "No mariadb hostname; skipping database wait."
		return 0
	fi
	host="${DB_HOST:-mariadb}"
	user="${DB_ROOT_USERNAME:-root}"
	pass="${DB_ROOT_PASSWORD:-123}"
	i=0
	while [ "$i" -lt 60 ]; do
		if command -v mariadb >/dev/null 2>&1 &&
			MYSQL_PWD="$pass" mariadb -h "$host" -u "$user" --connect-timeout=2 -e "SELECT 1" >/dev/null 2>&1; then
			return 0
		fi
		i=$((i + 1))
		sleep 2
	done
	cohenix_log "MariaDB at $host did not become ready in time." >&2
	return 1
}

cohenix_sync() {
	if cohenix_truthy "${COHENIX_SKIP_AUTOSYNC:-}"; then
		cohenix_log "Skipping automatic devctl sync (COHENIX_SKIP_AUTOSYNC is set)."
		return 0
	fi
	cohenix_run_devctl sync
}

cohenix_start() {
	if command -v devctl >/dev/null 2>&1 || python3 -c "import cohenix_dev" >/dev/null 2>&1; then
		cohenix_run_devctl start
		return
	fi
	# Fallback for an image that does not yet have the CLI on PATH.
	BENCH_NAME="${BENCH_NAME:-development-bench}"
	PILOT_DIR="${PILOT_DIR:-/home/frappe/pilot}"
	PID_FILE="/tmp/pilot-${BENCH_NAME}.pid"
	LOG_FILE="/tmp/pilot-${BENCH_NAME}.log"
	PILOT_BIN="${PILOT_DIR}/bin/pilot"
	if [ ! -x "$PILOT_BIN" ]; then
		printf 'Pilot is not installed at %s; run devctl sync first.\n' "$PILOT_BIN" >&2
		return 1
	fi
	if [ -s "$PID_FILE" ]; then
		pid="$(sed -n '1p' "$PID_FILE")"
		case "$pid" in
		*[!0-9]* | '') pid='' ;;
		esac
		if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
			printf 'Pilot bench %s is already running as PID %s.\n' "$BENCH_NAME" "$pid"
			return 0
		fi
	fi
	nohup "$PILOT_BIN" -b "$BENCH_NAME" start >"$LOG_FILE" 2>&1 </dev/null &
	pid=$!
	printf '%s\n' "$pid" >"$PID_FILE"
	sleep 2
	if ! kill -0 "$pid" 2>/dev/null; then
		printf 'Pilot failed to start. Recent output from %s:\n' "$LOG_FILE" >&2
		tail -n 40 "$LOG_FILE" >&2
		return 1
	fi
	printf 'Pilot bench %s started as PID %s (log: %s).\n' "$BENCH_NAME" "$pid" "$LOG_FILE"
}

cohenix_doctor() {
	if cohenix_truthy "${COHENIX_SKIP_DOCTOR:-}"; then
		cohenix_log "Skipping automatic devctl doctor (COHENIX_SKIP_DOCTOR is set)."
		return 0
	fi
	# Web, workers, and Socket.IO can take a few seconds after Pilot forks.
	i=0
	while [ "$i" -lt 15 ]; do
		if cohenix_run_devctl doctor; then
			site="${SITE_NAME:-cohenix.localhost}"
			port="${HTTP_PORT:-8000}"
			cohenix_log "Ready: http://${site}:${port}/app  (Administrator / admin)"
			return 0
		fi
		i=$((i + 1))
		sleep 2
	done
	cohenix_log "devctl doctor is still unhealthy. The editor will open; run \`devctl doctor\`." >&2
	return 1
}

cohenix_install_live_cli() {
	PYTHON="${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python}"
	PYTHON="${PYTHON:-$(command -v python3)}"
	uv pip install --python "$PYTHON" -e /workspace
	hash -r 2>/dev/null || true
}

cohenix_optional_precommit() {
	if [ ! -f /workspace/.pre-commit-config.yaml ]; then
		return 0
	fi
	if ! command -v pre-commit >/dev/null 2>&1; then
		uv tool install pre-commit >/dev/null 2>&1 || cohenix_log "pre-commit not installed (optional)"
	fi
	pre-commit install --install-hooks >/dev/null 2>&1 || true
}
