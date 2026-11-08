#!/usr/bin/env bash
# Per-boot start for Cursor Cloud Agents. Idempotent.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${PYTHONPATH:-$ROOT}"
export PILOT_DIR="${PILOT_DIR:-/home/frappe/pilot}"
export COHENIX_WORKSPACE="${COHENIX_WORKSPACE:-$ROOT}"

if command -v devctl >/dev/null 2>&1 && getent hosts mariadb >/dev/null 2>&1; then
	exec /workspace/scripts/start-dev.sh
fi

if ! command -v docker >/dev/null 2>&1; then
	printf '%s\n' "Docker is not available; cannot start the Frappe stack." >&2
	exit 0
fi

COMPOSE=(docker compose -f "$ROOT/.devcontainer/docker-compose.yml")
"${COMPOSE[@]}" up -d mariadb frappe
"${COMPOSE[@]}" exec -T frappe /workspace/scripts/start-dev.sh
