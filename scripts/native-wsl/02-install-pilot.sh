#!/usr/bin/env bash
# Install a pinned Pilot release tarball into ~/pilot (checksum verified).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

[[ "$(id -u)" -ne 0 ]] || die "Do not install Pilot as root"

ensure_repo
TOOLCHAIN="$COHENIX_REPO_DIR/toolchain.toml"
PILOT_VERSION="${PILOT_VERSION:-$(toolchain_get "$TOOLCHAIN" "pilot.native_wsl" "version")}"
PILOT_SHA256="${PILOT_SHA256:-$(toolchain_get "$TOOLCHAIN" "pilot.native_wsl" "sha256")}"
[[ -n "$PILOT_VERSION" ]] || die "Missing [pilot.native_wsl].version in toolchain.toml"
[[ -n "$PILOT_SHA256" ]] || die "Missing [pilot.native_wsl].sha256 in toolchain.toml"

VERSION_FILE="$PILOT_DIR/VERSION"
if [[ -x "$PILOT_DIR/bin/pilot" && -f "$VERSION_FILE" ]]; then
  installed="$(tr -d '[:space:]' < "$VERSION_FILE")"
  if [[ "$installed" == "$PILOT_VERSION" ]]; then
    log INFO "Pilot $installed already installed"
    mark_stage pilot_install
    exit 0
  fi
  die "Pilot version mismatch: found $installed, want $PILOT_VERSION. Remove $PILOT_DIR to upgrade intentionally."
fi

url="https://github.com/frappe/pilot/releases/download/${PILOT_VERSION}/pilot.tar.gz"
tmp="$(mktemp)"
log INFO "Downloading Pilot ${PILOT_VERSION}..."
curl -fsSL --proto '=https' --tlsv1.2 -o "$tmp" "$url"
actual="$(sha256sum "$tmp" | awk '{print $1}')"
if [[ "$actual" != "$PILOT_SHA256" ]]; then
  rm -f "$tmp"
  die "Pilot checksum mismatch: expected $PILOT_SHA256 got $actual"
fi

mkdir -p "$PILOT_DIR"
tar -xzf "$tmp" -C "$PILOT_DIR"
rm -f "$tmp"
chmod 755 "$PILOT_DIR/bin/pilot" || true

# CLI deps for host Python (Pilot CLI needs packaging/pymysql on some releases).
python3 -m pip install --user --quiet --disable-pip-version-check packaging pymysql 2>/dev/null || true

# PATH for login shells
for rc in "$HOME/.bashrc" "$HOME/.profile"; do
  touch "$rc"
  grep -q 'cohenix-pilot PATH' "$rc" 2>/dev/null || cat >>"$rc" <<EOF
# cohenix-pilot PATH
export PATH="\$HOME/.local/bin:\$HOME/pilot/bin:\$PATH"
EOF
done

export PATH="$HOME/.local/bin:$PILOT_DIR/bin:$PATH"
"$(pilot_bin)" --help >/dev/null
log INFO "Pilot $(tr -d '[:space:]' < "$VERSION_FILE") installed at $PILOT_DIR"
mark_stage pilot_install
