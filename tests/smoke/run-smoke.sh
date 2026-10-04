#!/bin/sh
# Environment smoke test for CI and cloud agents.
# Expects the frappe compose service to be running and reachable via docker compose.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT/.devcontainer/docker-compose.yml"
PROJECT="${COMPOSE_PROJECT_NAME:-cohenix-smoke}"
PROFILE="${COHENIX_PROFILE:-hr}"
SITE="${SITE_NAME:-cohenix.localhost}"
SECOND_SITE="${SECOND_SITE:-second.localhost}"

cd "$ROOT"

log() { printf '%s\n' "$*"; }

compose() {
	docker compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"
}

exec_frappe() {
	compose exec -T frappe bash -lc "$*"
}

log "==> Starting the development stack"
compose up -d --build mariadb frappe

log "==> Waiting for MariaDB"
i=0
while [ "$i" -lt 60 ]; do
	if compose exec -T mariadb healthcheck.sh --connect --innodb_initialized >/dev/null 2>&1; then
		break
	fi
	i=$((i + 1))
	sleep 2
done

log "==> Installing CLI and provisioning ($PROFILE)"
START=$(date +%s)
exec_frappe "sudo chown -R frappe:frappe /home/frappe/pilot /home/frappe/.cache /home/frappe/.npm || true"
exec_frappe "python3 -m pip install --user --disable-pip-version-check -e /workspace"
exec_frappe "devctl profile use $PROFILE"
exec_frappe "devctl sync --extra-sites $SECOND_SITE"
SYNC_END=$(date +%s)
FRESH_SECONDS=$((SYNC_END - START))
log "Fresh provisioning: ${FRESH_SECONDS}s"

log "==> Starting processes"
exec_frappe "devctl start" || true
sleep 8

log "==> HTTP ping"
exec_frappe "python3 - <<'PY'
import urllib.request
req = urllib.request.Request('http://127.0.0.1:8000/api/method/frappe.ping', headers={'Host': '$SITE'})
print(urllib.request.urlopen(req, timeout=20).read().decode())
PY"

log "==> Host-based routing for $SECOND_SITE"
exec_frappe "python3 - <<'PY'
import urllib.request
req = urllib.request.Request('http://127.0.0.1:8000/api/method/frappe.ping', headers={'Host': '$SECOND_SITE'})
print(urllib.request.urlopen(req, timeout=20).read().decode())
PY"

log "==> doctor / verify"
exec_frappe "devctl verify"
exec_frappe "devctl doctor" || true

log "==> Repeat sync (idempotency)"
REPEAT_START=$(date +%s)
exec_frappe "devctl sync"
REPEAT_END=$(date +%s)
REPEAT_SECONDS=$((REPEAT_END - REPEAT_START))
log "Repeat provisioning: ${REPEAT_SECONDS}s"
if [ "$REPEAT_SECONDS" -ge "$FRESH_SECONDS" ] && [ "$FRESH_SECONDS" -gt 30 ]; then
	log "WARNING: repeat sync was not faster than fresh provisioning"
fi

log "==> Restart container and confirm persistence"
compose restart frappe
sleep 5
exec_frappe "devctl start" || true
sleep 8
exec_frappe "test -f /home/frappe/pilot/benches/development-bench/sites/$SITE/site_config.json"
exec_frappe "python3 - <<'PY'
import urllib.request
req = urllib.request.Request('http://127.0.0.1:8000/api/method/frappe.ping', headers={'Host': '$SITE'})
print(urllib.request.urlopen(req, timeout=20).read().decode())
PY"

log "==> Unit smoke tests inside the container"
exec_frappe "COHENIX_SMOKE=1 python3 -m unittest tests.smoke.test_environment -v"

printf 'FRESH_SECONDS=%s\nREPEAT_SECONDS=%s\n' "$FRESH_SECONDS" "$REPEAT_SECONDS" > "$ROOT/docs/last-smoke-metrics.txt"
log "Smoke tests passed. Fresh=${FRESH_SECONDS}s Repeat=${REPEAT_SECONDS}s"
