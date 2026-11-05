#!/usr/bin/env bash
# Shared helpers for Cohenix native-WSL provisioners.
# shellcheck disable=SC2034
set -euo pipefail

COHENIX_NATIVE_ROOT="${COHENIX_NATIVE_ROOT:-$HOME/cohenix}"
COHENIX_REPO_DIR="${COHENIX_REPO_DIR:-$COHENIX_NATIVE_ROOT/frappe_cohenix_development}"
PILOT_DIR="${PILOT_DIR:-$HOME/pilot}"
BENCH_NAME="${BENCH_NAME:-development-bench}"
SITE_NAME="${SITE_NAME:-cohenix.localhost}"
PROFILE="${PROFILE:-hr}"
HTTP_PORT="${HTTP_PORT:-8000}"
SOCKETIO_PORT="${SOCKETIO_PORT:-9000}"
ADMIN_PORT="${ADMIN_PORT:-8002}"
STATE_DIR="${STATE_DIR:-$HOME/.cohenix-pilot}"
LOG_FILE="${LOG_FILE:-$STATE_DIR/provision.log}"

mkdir -p "$STATE_DIR"
touch "$LOG_FILE"

log() {
  local level="$1"; shift
  local msg="$*"
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf '%s [%s] %s\n' "$ts" "$level" "$msg" | tee -a "$LOG_FILE" >&2
}

die() {
  log ERROR "$*"
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

# Reject values that could break shell/wsl quoting if ever interpolated poorly.
validate_ident() {
  local name="$1" value="$2"
  [[ "$value" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || die "Invalid $name: $value"
}

validate_site() {
  local value="$1"
  [[ "$value" =~ ^[A-Za-z0-9][A-Za-z0-9.-]{0,126}$ ]] || die "Invalid site name: $value"
}

validate_port() {
  local value="$1"
  [[ "$value" =~ ^[0-9]+$ ]] && (( value >= 1 && value <= 65535 )) || die "Invalid port: $value"
}

validate_profile() {
  local value="$1"
  case "$value" in
    frappe|erp|hr|localisation|integrations|full-cohenix) ;;
    *) die "Unknown profile: $value" ;;
  esac
}

stage_marker() {
  echo "$STATE_DIR/stage.$1.done"
}

mark_stage() {
  date -u +"%Y-%m-%dT%H:%M:%SZ" > "$(stage_marker "$1")"
  log INFO "Stage complete: $1"
}

stage_done() {
  [[ -f "$(stage_marker "$1")" ]]
}

redact() {
  # Strip common secret patterns from streamed lines before UI display.
  sed -E \
    -e 's/(password(=|:)\s*)\S+/\1*** /gi' \
    -e 's/(passwd(=|:)\s*)\S+/\1*** /gi' \
    -e 's/(token(=|:)\s*)\S+/\1*** /gi' \
    -e 's/(secret(=|:)\s*)\S+/\1*** /gi' \
    -e 's/(sid=)[^&\s]+/\1***/gi'
}

ensure_repo() {
  if [[ -f "$COHENIX_REPO_DIR/config/profiles.toml" ]]; then
    log INFO "Cohenix repo present at $COHENIX_REPO_DIR"
    return 0
  fi
  mkdir -p "$COHENIX_NATIVE_ROOT"
  if [[ -n "${COHENIX_REPO_URL:-}" ]]; then
    log INFO "Cloning Cohenix repo..."
    git clone --depth 1 --branch "${COHENIX_REPO_BRANCH:-version-16_cohenix}" \
      "$COHENIX_REPO_URL" "$COHENIX_REPO_DIR"
  else
    die "Cohenix repo not found at $COHENIX_REPO_DIR and COHENIX_REPO_URL is unset"
  fi
}

toolchain_get() {
  # Minimal TOML peek without Python dependency during early bootstrap.
  local file="$1" section="$2" key="$3"
  awk -v section="$section" -v key="$key" '
    $0 ~ "^\\[" section "\\]" { insec=1; next }
    $0 ~ /^\[/ { insec=0 }
    insec && $1 == key {
      sub(/^[^=]*=[[:space:]]*/, "")
      gsub(/"/, "")
      print
      exit
    }
  ' "$file"
}

pilot_bin() {
  if [[ -x "$PILOT_DIR/bin/pilot" ]]; then
    echo "$PILOT_DIR/bin/pilot"
  elif command -v pilot >/dev/null 2>&1; then
    command -v pilot
  else
    die "Pilot binary not found under $PILOT_DIR/bin/pilot"
  fi
}

export PATH="$HOME/.local/bin:$PILOT_DIR/bin:$PATH"
