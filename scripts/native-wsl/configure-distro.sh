#!/usr/bin/env bash
# First-boot configuration for the Cohenix-Pilot WSL distro (idempotent).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

WSL_CONF="/etc/wsl.conf"

write_wsl_conf() {
  if [[ "$(id -u)" -ne 0 ]]; then
    die "configure-distro.sh must run as root once to write /etc/wsl.conf"
  fi
  cat > "$WSL_CONF" <<'EOF'
[boot]
systemd=true

[user]
default=cohenix

[network]
generateResolvConf=true

[interop]
enabled=true
appendWindowsPath=false
EOF
  log INFO "Wrote $WSL_CONF (systemd enabled; default user cohenix)"
}

ensure_user() {
  local user="${1:-cohenix}"
  if id "$user" >/dev/null 2>&1; then
    log INFO "User $user already exists"
  else
    useradd -m -s /bin/bash "$user"
    usermod -aG sudo "$user"
    # Passwordless sudo for package stages during guided setup only.
    echo "$user ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$user-cohenix"
    chmod 440 "/etc/sudoers.d/90-$user-cohenix"
    log INFO "Created user $user with sudo"
  fi
}

ACTION="${1:-all}"
case "$ACTION" in
  wsl-conf) write_wsl_conf ;;
  user) ensure_user "${2:-cohenix}" ;;
  all)
    write_wsl_conf
    ensure_user cohenix
    ;;
  *) die "Usage: $0 {all|wsl-conf|user [name]}" ;;
esac

mark_stage distro_configure
