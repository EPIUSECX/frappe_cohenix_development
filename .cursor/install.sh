#!/usr/bin/env bash
# Cursor Cloud Agent / Codespaces bootstrap.
# Prefers an already-running Dev Container (devctl on PATH). Otherwise brings
# the Compose stack up and provisions with the same lifecycle as postCreate.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="${PYTHONPATH:-$ROOT}"
export PILOT_DIR="${PILOT_DIR:-/home/frappe/pilot}"
export COHENIX_WORKSPACE="${COHENIX_WORKSPACE:-$ROOT}"

if command -v uv >/dev/null 2>&1; then
	uv pip install --python "${VIRTUAL_ENV:-$(command -v python3)}" -e "$ROOT" >/dev/null
elif command -v python3 >/dev/null 2>&1; then
	python3 -m pip install -e "$ROOT" >/dev/null 2>&1 || true
fi

# Already inside the Frappe Dev Container (Compose service `frappe`).
if command -v devctl >/dev/null 2>&1 && getent hosts mariadb >/dev/null 2>&1; then
	# shellcheck source=/dev/null
	. "$ROOT/scripts/cohenix-lifecycle.sh"
	cohenix_wait_for_mariadb
	cohenix_sync
	exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
	printf '%s\n' "Docker is required outside the Dev Container. Install Docker, then reopen." >&2
	exit 1
fi

COMPOSE=(docker compose -f "$ROOT/.devcontainer/docker-compose.yml")
"${COMPOSE[@]}" up -d --build mariadb frappe
# Wait for the frappe service, then run the same postCreate path inside it.
for _ in $(seq 1 60); do
	if "${COMPOSE[@]}" exec -T frappe true >/dev/null 2>&1; then
		break
	fi
	sleep 2
done
"${COMPOSE[@]}" exec -T frappe /workspace/scripts/post-create.sh
