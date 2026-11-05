#!/usr/bin/env bash
# Backup a site before migrations or destructive operations.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

SITE="${1:-$SITE_NAME}"
validate_site "$SITE"
validate_ident "bench" "$BENCH_NAME"
export PATH="$HOME/.local/bin:$PILOT_DIR/bin:$PATH"
PILOT="$(pilot_bin)"
DEST="$STATE_DIR/backups"
mkdir -p "$DEST"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out="$DEST/${SITE}.${stamp}"
mkdir -p "$out"

log INFO "Backing up site $SITE to $out"
"$PILOT" --bench "$BENCH_NAME" frappe --site "$SITE" backup --with-files --backup-path-db "$out" \
  || "$PILOT" --bench "$BENCH_NAME" frappe --site "$SITE" backup --with-files

# Also copy site_config (no secrets printed)
if [[ -f "$PILOT_DIR/benches/$BENCH_NAME/sites/$SITE/site_config.json" ]]; then
  cp "$PILOT_DIR/benches/$BENCH_NAME/sites/$SITE/site_config.json" "$out/site_config.json"
  chmod 600 "$out/site_config.json"
fi

log INFO "Backup complete: $out"
echo "$out"
