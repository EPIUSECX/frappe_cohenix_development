#!/usr/bin/env bash
# Install native Ubuntu 24.04 dependencies for Frappe Pilot (no Docker).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

NODE_VERSION="${NODE_VERSION:-24.12.0}"
UV_VERSION="${UV_VERSION:-0.11.33}"
YARN_VERSION="${YARN_VERSION:-1.22.22}"

if stage_done system_deps && command -v node >/dev/null && command -v mariadbd >/dev/null; then
  log INFO "system_deps already satisfied"
  exit 0
fi

if [[ "$(id -u)" -eq 0 ]]; then
  AS_ROOT=1
  run_pkg() { "$@"; }
else
  AS_ROOT=0
  run_pkg() { sudo DEBIAN_FRONTEND=noninteractive "$@"; }
fi

log INFO "Installing apt packages for native Cohenix Pilot..."
run_pkg apt-get update -y
run_pkg apt-get install -y --no-install-recommends \
  ca-certificates curl wget gnupg git build-essential \
  python3 python3-venv python3-pip python3-dev \
  libffi-dev libssl-dev libjpeg-dev zlib1g-dev liblcms2-dev \
  libldap2-dev libsasl2-dev libtiff5-dev libwebp-dev \
  libpq-dev pkg-config \
  redis-server \
  mariadb-server mariadb-client libmariadb-dev \
  fontconfig libxrender1 xfonts-75dpi xfonts-base \
  xvfb libnss3 libatk-bridge2.0-0 libgtk-3-0 \
  jq unzip tar xz-utils \
  software-properties-common

# MariaDB must accept local TCP for Pilot (bind loopback).
if [[ -d /etc/mysql/mariadb.conf.d ]]; then
  cat <<'EOF' | run_pkg tee /etc/mysql/mariadb.conf.d/99-cohenix-pilot.cnf >/dev/null
[mysqld]
bind-address = 127.0.0.1
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
EOF
fi

if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
  run_pkg systemctl enable mariadb redis-server || true
  run_pkg systemctl start mariadb redis-server || true
else
  log INFO "systemd not fully available; starting MariaDB/Redis via service if present"
  run_pkg service mariadb start || true
  run_pkg service redis-server start || true
fi

# Node official tarball (matches toolchain.toml); avoid apt Node 18.
install_node() {
  if command -v node >/dev/null 2>&1; then
    local major
    major="$(node -v | tr -d v | cut -d. -f1)"
    if [[ "$major" -ge 24 ]]; then
      log INFO "Node $(node -v) already installed"
      return 0
    fi
  fi
  local arch url tmp
  arch="$(uname -m)"
  case "$arch" in
    x86_64) arch=x64 ;;
    aarch64) arch=arm64 ;;
    *) die "Unsupported arch for Node: $arch" ;;
  esac
  url="https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${arch}.tar.xz"
  tmp="$(mktemp -d)"
  log INFO "Installing Node ${NODE_VERSION} from nodejs.org..."
  curl -fsSL "$url" -o "$tmp/node.tar.xz"
  run_pkg tar -xJf "$tmp/node.tar.xz" -C /usr/local --strip-components=1
  rm -rf "$tmp"
  node -v
  npm -v
}

install_node

if ! command -v yarn >/dev/null 2>&1; then
  log INFO "Installing Yarn ${YARN_VERSION}"
  npm install -g "yarn@${YARN_VERSION}"
fi

if ! command -v uv >/dev/null 2>&1; then
  log INFO "Installing uv ${UV_VERSION}"
  curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

# Ensure a non-root login user can manage DB for Pilot first-run.
if [[ -n "${COHENIX_DB_ROOT_PASSWORD:-}" ]]; then
  log INFO "Configuring MariaDB root authentication for local Pilot..."
  # Prefer socket sudo mysql as root, then set a password for TCP root@localhost.
  if [[ "$AS_ROOT" -eq 1 ]]; then
    mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('${COHENIX_DB_ROOT_PASSWORD}'); FLUSH PRIVILEGES;" \
      || mysql -e "SET PASSWORD FOR 'root'@'localhost' = PASSWORD('${COHENIX_DB_ROOT_PASSWORD}'); FLUSH PRIVILEGES;" \
      || true
  else
    sudo mysql -e "ALTER USER 'root'@'localhost' IDENTIFIED VIA mysql_native_password USING PASSWORD('${COHENIX_DB_ROOT_PASSWORD}'); FLUSH PRIVILEGES;" \
      || sudo mysql -e "SET PASSWORD FOR 'root'@'localhost' = PASSWORD('${COHENIX_DB_ROOT_PASSWORD}'); FLUSH PRIVILEGES;" \
      || true
  fi
fi

mark_stage system_deps
log INFO "Native system dependencies ready"
