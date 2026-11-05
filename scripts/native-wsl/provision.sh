#!/usr/bin/env bash
# Orchestrate native WSL stages. Idempotent; safe to re-run.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

STAGE="all"
PROFILE="${PROFILE:-hr}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --stage) STAGE="$2"; shift 2 ;;
    --site) SITE_NAME="$2"; shift 2 ;;
    --bench) BENCH_NAME="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--profile hr] [--stage all|system_deps|pilot_install|cohenix_provision|verify|start] [--site name] [--bench name]"
      exit 0
      ;;
    *) die "Unknown arg: $1" ;;
  esac
done

validate_profile "$PROFILE"
export PROFILE SITE_NAME BENCH_NAME

run_stage() {
  local name="$1"
  shift
  log INFO ">>> stage $name"
  "$@"
  log INFO "<<< stage $name done"
}

case "$STAGE" in
  all)
    run_stage system_deps bash "$SCRIPT_DIR/01-system-deps.sh"
    run_stage pilot_install bash "$SCRIPT_DIR/02-install-pilot.sh"
    run_stage cohenix_provision bash "$SCRIPT_DIR/03-provision-cohenix.sh" "$PROFILE"
    run_stage start bash "$SCRIPT_DIR/lifecycle.sh" start
    # Give processes a moment before health probes.
    sleep 5
    run_stage verify bash "$SCRIPT_DIR/04-health.sh"
    ;;
  system_deps) run_stage system_deps bash "$SCRIPT_DIR/01-system-deps.sh" ;;
  pilot_install) run_stage pilot_install bash "$SCRIPT_DIR/02-install-pilot.sh" ;;
  cohenix_provision) run_stage cohenix_provision bash "$SCRIPT_DIR/03-provision-cohenix.sh" "$PROFILE" ;;
  start) run_stage start bash "$SCRIPT_DIR/lifecycle.sh" start ;;
  verify) run_stage verify bash "$SCRIPT_DIR/04-health.sh" ;;
  *) die "Unknown stage: $STAGE" ;;
esac
