#!/usr/bin/env bash
# Provision Pilot bench + Cohenix site from profiles.toml (idempotent, no Docker).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

[[ "$(id -u)" -ne 0 ]] || die "Provision as the normal WSL user, not root"

PROFILE="${1:-${PROFILE:-hr}}"
validate_profile "$PROFILE"
validate_ident "bench" "$BENCH_NAME"
validate_site "$SITE_NAME"
validate_port "$HTTP_PORT"
validate_port "$SOCKETIO_PORT"
validate_port "$ADMIN_PORT"

: "${COHENIX_ADMIN_UI_PASSWORD:?COHENIX_ADMIN_UI_PASSWORD is required}"
: "${COHENIX_SITE_ADMIN_PASSWORD:?COHENIX_SITE_ADMIN_PASSWORD is required}"
: "${COHENIX_DB_ROOT_PASSWORD:?COHENIX_DB_ROOT_PASSWORD is required}"

ensure_repo
export PATH="$HOME/.local/bin:$PILOT_DIR/bin:$PATH"
PILOT="$(pilot_bin)"
BENCH_ROOT="$PILOT_DIR/benches/$BENCH_NAME"
PROFILES="$COHENIX_REPO_DIR/config/profiles.toml"
PY_VERSION="$(toolchain_get "$COHENIX_REPO_DIR/toolchain.toml" "python" "version" || true)"
PY_VERSION="${PY_VERSION:-3.14.2}"
# Pilot bench.python often wants major.minor
PY_MAJOR_MINOR="$(echo "$PY_VERSION" | cut -d. -f1-2)"

log INFO "Resolving profile $PROFILE"
APPS_TOML="$STATE_DIR/apps.$PROFILE.toml"
python3 "$SCRIPT_DIR/resolve_profile.py" --profiles "$PROFILES" --profile "$PROFILE" --toml-apps > "$APPS_TOML"
APP_NAMES="$(python3 "$SCRIPT_DIR/resolve_profile.py" --profiles "$PROFILES" --profile "$PROFILE" \
  | python3 -c 'import json,sys; print(" ".join(a["name"] for a in json.load(sys.stdin)["apps"]))')"

if [[ ! -f "$BENCH_ROOT/bench.toml" ]]; then
  log INFO "Creating bench $BENCH_NAME"
  "$PILOT" new "$BENCH_NAME" --database mariadb --admin-password "$COHENIX_ADMIN_UI_PASSWORD"
fi

log INFO "Writing bench.toml for profile $PROFILE"
cat > "$BENCH_ROOT/bench.toml" <<EOF
[bench]
name = "$BENCH_NAME"
python = "$PY_MAJOR_MINOR"
http_port = $HTTP_PORT
socketio_port = $SOCKETIO_PORT
socketio_backend = "node"
db_type = "mariadb"
allow_developer_mode = true
default_branch = "version-16"

$(cat "$APPS_TOML")
[mariadb]
host = "127.0.0.1"
port = 3306
admin_user = "root"
root_password = "$COHENIX_DB_ROOT_PASSWORD"
socket_path = ""
existing = true

[redis]
cache_port = 13000
queue_port = 11000

[[workers]]
queues = ["default", "short", "long"]
count = 1

[admin]
enabled = true
port = $ADMIN_PORT
password = "$COHENIX_ADMIN_UI_PASSWORD"
domain = ""
tls = false
allow_bench_management = true
EOF
chmod 600 "$BENCH_ROOT/bench.toml"

if [[ ! -d "$BENCH_ROOT/apps/frappe" ]]; then
  log INFO "Running pilot init (clone + install apps)..."
  "$PILOT" --bench "$BENCH_NAME" init
else
  log INFO "Bench apps already present; skipping init"
fi

# Developer mode in common site config
COMMON="$BENCH_ROOT/sites/common_site_config.json"
if [[ -f "$COMMON" ]]; then
  python3 - <<PY
import json
from pathlib import Path
p = Path("$COMMON")
data = json.loads(p.read_text())
data["developer_mode"] = 1
data["default_site"] = "$SITE_NAME"
data["serve_default_site"] = True
p.write_text(json.dumps(data, indent=1) + "\n")
PY
fi

if [[ -d "$BENCH_ROOT/sites/$SITE_NAME" ]]; then
  log INFO "Site $SITE_NAME already exists; ensuring apps..."
  # shellcheck disable=SC2086
  missing=""
  for app in $APP_NAMES; do
    if ! "$PILOT" --bench "$BENCH_NAME" list-site-apps "$SITE_NAME" 2>/dev/null | grep -qw "$app"; then
      missing="$missing $app"
    fi
  done
  if [[ -n "${missing// }" ]]; then
    # shellcheck disable=SC2086
    "$PILOT" --bench "$BENCH_NAME" install-app "$SITE_NAME" $missing
  fi
else
  log INFO "Creating site $SITE_NAME with apps: $APP_NAMES"
  # shellcheck disable=SC2086
  "$PILOT" --bench "$BENCH_NAME" new-site "$SITE_NAME" \
    --admin-password "$COHENIX_SITE_ADMIN_PASSWORD" \
    --apps $APP_NAMES
fi

echo "$PROFILE" > "$STATE_DIR/profile"
echo "$SITE_NAME" > "$STATE_DIR/site"
echo "$BENCH_NAME" > "$STATE_DIR/bench"
mark_stage cohenix_provision
log INFO "Cohenix provision complete for profile=$PROFILE site=$SITE_NAME"
