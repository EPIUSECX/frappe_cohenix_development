#!/usr/bin/env bash
# Verify native WSL Cohenix Pilot stack. Exit 0 only when checks pass.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

export PATH="$HOME/.local/bin:$PILOT_DIR/bin:$PATH"
HTTP_PORT="${HTTP_PORT:-8000}"
ADMIN_PORT="${ADMIN_PORT:-8002}"
SITE_NAME="${SITE_NAME:-cohenix.localhost}"
BENCH_NAME="${BENCH_NAME:-development-bench}"
failures=0

check() {
  local name="$1"; shift
  if "$@"; then
    log INFO "OK  $name"
  else
    log ERROR "FAIL $name"
    failures=$((failures + 1))
  fi
}

check "pilot binary" test -x "$(pilot_bin 2>/dev/null || echo /nonexistent)"
check "bench.toml" test -f "$PILOT_DIR/benches/$BENCH_NAME/bench.toml"
check "frappe app" test -d "$PILOT_DIR/benches/$BENCH_NAME/apps/frappe"
check "site dir" test -d "$PILOT_DIR/benches/$BENCH_NAME/sites/$SITE_NAME"

if command -v redis-cli >/dev/null; then
  check "redis ping" bash -c 'redis-cli ping | grep -q PONG'
fi
if command -v mysql >/dev/null; then
  check "mariadb ping" bash -c 'mysqladmin ping --silent 2>/dev/null || mysqladmin ping -h127.0.0.1 --silent 2>/dev/null'
fi

check "frappe http" bash -c "curl -fsS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:${HTTP_PORT}/api/method/frappe.ping | grep -E '200|417|404|403' >/dev/null"
# Pilot Admin health is unauthenticated per upstream docs.
check "pilot admin health" bash -c "curl -fsS --max-time 5 http://127.0.0.1:${ADMIN_PORT}/health >/dev/null"

if [[ -d "$PILOT_DIR/benches/$BENCH_NAME/apps/erpnext" ]]; then
  check "erpnext present" true
fi
if [[ -d "$PILOT_DIR/benches/$BENCH_NAME/apps/hrms" ]]; then
  check "hrms present" true
fi

if [[ "$failures" -gt 0 ]]; then
  log ERROR "$failures health check(s) failed"
  exit 1
fi

mark_stage verify
log INFO "All health checks passed"
printf '{"ok":true,"site":"%s","http_port":%s,"admin_port":%s}\n' \
  "$SITE_NAME" "$HTTP_PORT" "$ADMIN_PORT"
