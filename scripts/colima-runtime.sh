#!/usr/bin/env bash
# Host container runtime for Cohenix Frappe development.
#
# Colima provides the Docker daemon on macOS, Linux, and Windows WSL2.
# This script does not install Docker Desktop or the docker-ce engine.
# GitHub Actions and GitHub Codespaces already have Docker Engine and are skipped.
#
#   bash scripts/colima-runtime.sh up
#   bash scripts/colima-runtime.sh status

set -euo pipefail

COLIMA_VERSION="${COLIMA_VERSION:-0.10.3}"
LIMA_VERSION="${LIMA_VERSION:-2.2.1}"

colima_runtime_root() {
	cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

colima_runtime_platform() {
	if [[ -n "${COLIMA_PLATFORM_OVERRIDE:-}" ]]; then
		printf '%s\n' "$COLIMA_PLATFORM_OVERRIDE"
		return
	fi
	local uname_s
	uname_s="$(uname -s)"
	case "$uname_s" in
	Darwin) printf 'macos\n' ;;
	Linux)
		if [[ -r /proc/version ]] && grep -qi microsoft /proc/version; then
			printf 'wsl\n'
		else
			printf 'linux\n'
		fi
		;;
	MINGW* | MSYS* | CYGWIN*) printf 'windows\n' ;;
	*) printf 'unsupported\n' ;;
	esac
}

# Lima and Colima release names for the current machine.
# Darwin arm64 is "arm64". Linux arm64 is "aarch64".
colima_runtime_release_arch() {
	local platform="$1"
	case "$(uname -m):$platform" in
	x86_64:* | amd64:*) printf 'x86_64\n' ;;
	arm64:macos | aarch64:macos) printf 'arm64\n' ;;
	aarch64:linux | aarch64:wsl | arm64:linux | arm64:wsl) printf 'aarch64\n' ;;
	*)
		echo "Unsupported CPU architecture: $(uname -m)" >&2
		return 1
		;;
	esac
}

# Mount the repo into the Colima VM. Home already covers a checkout under $HOME.
# A second mount is required when the checkout lives elsewhere (for example /workspace).
colima_runtime_mount_lines() {
	local home="$1"
	local repo="$2"
	case "$repo" in
	"$home" | "$home"/*)
		printf '%s:w\n' "$home"
		;;
	*)
		printf '%s:w\n' "$home"
		printf '%s:w\n' "$repo"
		;;
	esac
}

colima_runtime_skip_reason() {
	if [[ -n "${GITHUB_ACTIONS:-}" ]]; then
		printf '%s\n' "GitHub Actions already provides Docker Engine"
		return 0
	fi
	if [[ -n "${CODESPACES:-}" ]]; then
		printf '%s\n' "GitHub Codespaces already provides Docker Engine"
		return 0
	fi
	return 1
}

colima_runtime_default_cpus() {
	if [[ -n "${COLIMA_CPUS:-}" ]]; then
		printf '%s\n' "$COLIMA_CPUS"
		return
	fi
	local cpus
	cpus="$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf '2')"
	if [[ "$cpus" -gt 4 ]]; then
		cpus=4
	fi
	if [[ "$cpus" -lt 2 ]]; then
		cpus=2
	fi
	printf '%s\n' "$cpus"
}

colima_runtime_default_memory() {
	if [[ -n "${COLIMA_MEMORY:-}" ]]; then
		printf '%s\n' "$COLIMA_MEMORY"
		return
	fi
	local available=8
	if [[ -r /proc/meminfo ]]; then
		available="$(awk '/MemAvailable:/ { printf "%d", $2 / 1024 / 1024 }' /proc/meminfo)"
	elif command -v sysctl >/dev/null 2>&1; then
		local bytes
		bytes="$(sysctl -n hw.memsize 2>/dev/null || printf '0')"
		if [[ "$bytes" -gt 0 ]]; then
			available="$((bytes / 1024 / 1024 / 1024))"
		fi
	fi
	local memory=$((available - 2))
	if [[ "$memory" -gt 8 ]]; then
		memory=8
	fi
	if [[ "$memory" -lt 2 ]]; then
		memory=2
	fi
	printf '%s\n' "$memory"
}

colima_runtime_as_root() {
	if [[ "$(id -u)" -eq 0 ]]; then
		"$@"
	else
		sudo "$@"
	fi
}

colima_runtime_version_has() {
	local command_name="$1"
	local needle="$2"
	local output
	if ! command -v "$command_name" >/dev/null 2>&1; then
		return 1
	fi
	output="$("$command_name" version 2>&1 || true)"
	case "$output" in
	*"$needle"*) return 0 ;;
	*) return 1 ;;
	esac
}

colima_runtime_download() {
	local url="$1"
	local destination="$2"
	curl -fL --retry 3 -o "$destination" "$url"
}

colima_runtime_verify_sha256() {
	local file_path="$1"
	local expected="$2"
	echo "$expected  $file_path" | sha256sum -c -
}

colima_runtime_checksum_for() {
	local sums_file="$1"
	local asset_name="$2"
	awk -v name="$asset_name" '
		$2 == name || $2 == ("*" name) { print $1; found = 1; exit }
		END { if (!found) exit 1 }
	' "$sums_file"
}

colima_runtime_install_lima_colima() {
	local platform="$1"
	local arch asset_os work lima_output
	arch="$(colima_runtime_release_arch "$platform")"
	case "$platform" in
	macos) asset_os="Darwin" ;;
	linux | wsl) asset_os="Linux" ;;
	*) return 1 ;;
	esac

	work="$(mktemp -d)"
	lima_output="$(limactl --version 2>&1 || true)"
	case "$lima_output" in
	*"$LIMA_VERSION"*) ;;
	*)
		colima_runtime_download \
			"https://github.com/lima-vm/lima/releases/download/v${LIMA_VERSION}/SHA256SUMS" \
			"$work/SHA256SUMS"
		local lima_archive="lima-${LIMA_VERSION}-${asset_os}-${arch}.tar.gz"
		local agents_archive="lima-additional-guestagents-${LIMA_VERSION}-${asset_os}-${arch}.tar.gz"
		colima_runtime_download \
			"https://github.com/lima-vm/lima/releases/download/v${LIMA_VERSION}/${lima_archive}" \
			"$work/$lima_archive"
		colima_runtime_download \
			"https://github.com/lima-vm/lima/releases/download/v${LIMA_VERSION}/${agents_archive}" \
			"$work/$agents_archive"
		colima_runtime_verify_sha256 "$work/$lima_archive" "$(colima_runtime_checksum_for "$work/SHA256SUMS" "$lima_archive")"
		colima_runtime_verify_sha256 "$work/$agents_archive" "$(colima_runtime_checksum_for "$work/SHA256SUMS" "$agents_archive")"
		colima_runtime_as_root tar -C /usr/local -xzf "$work/$lima_archive"
		colima_runtime_as_root tar -C /usr/local -xzf "$work/$agents_archive"
		;;
	esac
	if ! colima_runtime_version_has colima "$COLIMA_VERSION"; then
		local colima_asset="colima-${asset_os}-${arch}"
		colima_runtime_download \
			"https://github.com/abiosoft/colima/releases/download/v${COLIMA_VERSION}/${colima_asset}" \
			"$work/$colima_asset"
		colima_runtime_download \
			"https://github.com/abiosoft/colima/releases/download/v${COLIMA_VERSION}/${colima_asset}.sha256sum" \
			"$work/${colima_asset}.sha256sum"
		local expected
		expected="$(awk '{ print $1; exit }' "$work/${colima_asset}.sha256sum")"
		colima_runtime_verify_sha256 "$work/$colima_asset" "$expected"
		colima_runtime_as_root install -m 0755 "$work/$colima_asset" /usr/local/bin/colima
	fi
	rm -rf "$work"
}

colima_runtime_install_docker_cli_apt() {
	if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 && docker buildx version >/dev/null 2>&1; then
		return 0
	fi
	if ! command -v apt-get >/dev/null 2>&1; then
		echo "Install the Docker client, Compose plugin, and Buildx plugin, then re-run this script." >&2
		echo "Do not install Docker Desktop or the docker-ce engine. Colima runs the daemon." >&2
		return 1
	fi
	local distro suite arch
	# shellcheck disable=SC1091
	. /etc/os-release
	case " ${ID:-} ${ID_LIKE:-} " in
	*" ubuntu "*)
		distro="ubuntu"
		suite="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
		;;
	*" debian "*)
		distro="debian"
		suite="${VERSION_CODENAME:-}"
		;;
	*)
		distro="ubuntu"
		suite="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"
		;;
	esac
	arch="$(dpkg --print-architecture)"
	colima_runtime_as_root install -m 0755 -d /etc/apt/keyrings
	colima_runtime_as_root curl -fsSL "https://download.docker.com/linux/${distro}/gpg" -o /etc/apt/keyrings/docker.asc
	colima_runtime_as_root chmod a+r /etc/apt/keyrings/docker.asc
	colima_runtime_as_root tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/${distro}
Suites: ${suite}
Components: stable
Architectures: ${arch}
Signed-By: /etc/apt/keyrings/docker.asc
EOF
	colima_runtime_as_root apt-get update -qq
	# Unpinned so Ubuntu 22.04 and 24.04 (including WSL) resolve their own builds.
	# docker-ce, the engine package, is intentionally absent. Colima runs dockerd.
	colima_runtime_as_root apt-get install -y --no-install-recommends \
		docker-ce-cli docker-buildx-plugin docker-compose-plugin
	if dpkg -s docker-ce >/dev/null 2>&1; then
		echo "The docker-ce engine is installed. Colima is the Docker runtime; remove docker-ce or leave its service stopped." >&2
		return 1
	fi
}

colima_runtime_install_linux_packages() {
	if command -v apt-get >/dev/null 2>&1; then
		if ! command -v qemu-system-x86_64 >/dev/null 2>&1 || [[ ! -e /usr/share/OVMF/OVMF_CODE_4M.fd && ! -e /usr/share/OVMF/OVMF_CODE.fd ]]; then
			colima_runtime_as_root apt-get update -qq
			colima_runtime_as_root apt-get install -y --no-install-recommends \
				ca-certificates curl qemu-system-x86 qemu-utils genisoimage ovmf
		fi
		colima_runtime_install_docker_cli_apt
		return
	fi
	if command -v dnf >/dev/null 2>&1; then
		colima_runtime_as_root dnf install -y qemu-kvm edk2-ovmf curl ca-certificates
	fi
	if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
		echo "Install the Docker client and Compose plugin with your package manager, then re-run this script." >&2
		echo "Example (Fedora): sudo dnf install docker-cli docker-compose-plugin" >&2
		echo "Do not install Docker Desktop. Colima runs the daemon." >&2
		return 1
	fi
}

colima_runtime_install_macos() {
	if ! command -v brew >/dev/null 2>&1; then
		echo "Homebrew is required on macOS. Install it from https://brew.sh and re-run this script." >&2
		return 1
	fi
	if ! command -v colima >/dev/null 2>&1 \
		|| ! command -v docker >/dev/null 2>&1 \
		|| ! docker compose version >/dev/null 2>&1 \
		|| ! docker buildx version >/dev/null 2>&1; then
		brew install colima docker docker-compose docker-buildx
	fi
	local prefix
	prefix="$(brew --prefix)"
	mkdir -p "${HOME}/.docker/cli-plugins"
	# Compose itself is replaced by the entitlement wrapper after install.
	if [[ -x "${prefix}/opt/docker-buildx/bin/docker-buildx" ]]; then
		ln -sfn "${prefix}/opt/docker-buildx/bin/docker-buildx" "${HOME}/.docker/cli-plugins/docker-buildx"
	fi
}

# Buildx 0.37.2 and later refuses a Dockerfile that lives outside the Compose
# project. VS Code writes that file under a temporary directory
# (Dockerfile-with-features) and does not pass --allow=fs.read. A Compose
# plugin wrapper sets BUILDX_BAKE_ENTITLEMENTS_FS=0 for every `docker compose`
# invocation, which is the upstream workaround:
# https://github.com/microsoft/vscode-remote-release/issues/11896
colima_runtime_compose_wrapper_marker() {
	printf '%s\n' "cohenix-buildx-entitlements"
}

colima_runtime_docker_config_dir() {
	if [[ -n "${DOCKER_CONFIG:-}" ]]; then
		printf '%s\n' "$DOCKER_CONFIG"
	else
		printf '%s\n' "${HOME}/.docker"
	fi
}

colima_runtime_shell_single_quote() {
	local value="$1"
	value="${value//\'/\'\\\'\'}"
	printf "'%s'" "$value"
}

colima_runtime_file_is_wrapper() {
	local path="$1"
	[[ -f "$path" && ! -L "$path" ]] || return 1
	grep -q "$(colima_runtime_compose_wrapper_marker)" "$path"
}

colima_runtime_compose_search_paths() {
	if [[ -n "${COLIMA_COMPOSE_PLUGIN_OVERRIDE:-}" ]]; then
		printf '%s\n' "$COLIMA_COMPOSE_PLUGIN_OVERRIDE"
	fi
	local prefix=""
	if command -v brew >/dev/null 2>&1; then
		prefix="$(brew --prefix 2>/dev/null || true)"
	fi
	if [[ -n "$prefix" ]]; then
		printf '%s\n' \
			"${prefix}/opt/docker-compose/bin/docker-compose" \
			"${prefix}/lib/docker/cli-plugins/docker-compose"
	fi
	printf '%s\n' \
		/opt/homebrew/opt/docker-compose/bin/docker-compose \
		/opt/homebrew/lib/docker/cli-plugins/docker-compose \
		/home/linuxbrew/.linuxbrew/opt/docker-compose/bin/docker-compose \
		/home/linuxbrew/.linuxbrew/lib/docker/cli-plugins/docker-compose \
		/usr/local/lib/docker/cli-plugins/docker-compose \
		/usr/local/libexec/docker/cli-plugins/docker-compose \
		/usr/lib/docker/cli-plugins/docker-compose \
		/usr/libexec/docker/cli-plugins/docker-compose
}

colima_runtime_find_compose_plugin() {
	local dest="$1"
	local candidate target
	while IFS= read -r candidate; do
		[[ -n "$candidate" && -x "$candidate" ]] || continue
		[[ "$candidate" == "$dest" ]] && continue
		if colima_runtime_file_is_wrapper "$candidate"; then
			continue
		fi
		printf '%s\n' "$candidate"
		return 0
	done <<EOF
$(colima_runtime_compose_search_paths)
EOF
	if [[ -L "$dest" ]]; then
		target="$(readlink "$dest")"
		case "$target" in
		/*) ;;
		*) target="$(cd "$(dirname "$dest")" && pwd)/${target}" ;;
		esac
		if [[ -x "$target" ]] && ! colima_runtime_file_is_wrapper "$target"; then
			printf '%s\n' "$target"
			return 0
		fi
	fi
	return 1
}

colima_runtime_write_compose_wrapper() {
	local real="$1"
	local dest="$2"
	local quoted
	quoted="$(colima_runtime_shell_single_quote "$real")"
	mkdir -p "$(dirname "$dest")"
	# dest is usually a symlink to the Homebrew binary; replace the link itself
	# instead of writing through it onto the real (read-only) executable.
	if [[ -L "$dest" ]]; then
		rm -f "$dest"
	fi
	cat > "$dest" <<EOF
#!/bin/sh
# $(colima_runtime_compose_wrapper_marker)
# Allows the Dev Container generated Dockerfile outside the build context.
# Remove this wrapper once Compose passes --allow=fs.read for that file.
if [ -z "\${BUILDX_BAKE_ENTITLEMENTS_FS+x}" ]; then
	BUILDX_BAKE_ENTITLEMENTS_FS=0
	export BUILDX_BAKE_ENTITLEMENTS_FS
fi
exec ${quoted} "\$@"
EOF
	chmod 755 "$dest"
}

colima_runtime_install_compose_wrapper() {
	local config dest real
	config="$(colima_runtime_docker_config_dir)"
	dest="${config}/cli-plugins/docker-compose"
	if [[ -e "$dest" && ! -L "$dest" ]] && ! colima_runtime_file_is_wrapper "$dest"; then
		echo "Leaving the existing Compose plugin in place: $dest" >&2
		echo "Set BUILDX_BAKE_ENTITLEMENTS_FS=0 in the environment that starts VS Code or Cursor." >&2
		return 0
	fi
	if ! real="$(colima_runtime_find_compose_plugin "$dest")"; then
		echo "Docker Compose plugin not found; skipping the Buildx entitlement wrapper." >&2
		return 0
	fi
	colima_runtime_write_compose_wrapper "$real" "$dest"
	echo "Compose will allow the Dev Container generated Dockerfile (BUILDX_BAKE_ENTITLEMENTS_FS=0)."
}

colima_runtime_install() {
	local platform="$1"
	case "$platform" in
	macos) colima_runtime_install_macos ;;
	linux | wsl)
		colima_runtime_install_linux_packages
		colima_runtime_install_lima_colima "$platform"
		;;
	*) return 1 ;;
	esac
}

colima_runtime_prepare_kvm() {
	local platform="$1"
	case "$platform" in
	linux | wsl) ;;
	*) return 0 ;;
	esac
	if [[ -x /usr/local/bin/qemu-system-x86_64-tcg ]]; then
		# This host cannot create a KVM vCPU. The wrapper forces software emulation.
		export QEMU_SYSTEM_X86_64=/usr/local/bin/qemu-system-x86_64-tcg
		return 0
	fi
	if [[ ! -e /dev/kvm ]]; then
		if [[ "$platform" == "wsl" ]]; then
			echo "WSL has no /dev/kvm. Colima will emulate the CPU in software and will be slow." >&2
			echo "Enable nested virtualization in %UserProfile%\\.wslconfig:" >&2
			echo "[wsl2]" >&2
			echo "nestedVirtualization=true" >&2
			echo "Then run: wsl --shutdown" >&2
		else
			echo "No /dev/kvm. Colima will emulate the CPU in software and will be slow." >&2
		fi
		return 0
	fi
	if [[ -w /dev/kvm ]]; then
		return 0
	fi
	local group_name
	group_name="$(stat -c '%G' /dev/kvm 2>/dev/null || printf 'kvm')"
	echo "Granting $USER access to /dev/kvm through the $group_name group." >&2
	colima_runtime_as_root usermod -aG "$group_name" "$USER" || true
	if [[ ! -w /dev/kvm ]]; then
		echo "Open a new shell so the $group_name group applies, then re-run this script." >&2
		echo "Or run: sg $group_name -c 'bash scripts/colima-runtime.sh up'" >&2
		return 1
	fi
}

colima_runtime_warn_wsl_mount() {
	local repo="$1"
	case "$repo" in
	/mnt/*)
		echo "This checkout is on a Windows drive ($repo)." >&2
		echo "Colima file sharing is much faster from the WSL filesystem, for example ~/src/frappe_cohenix_development." >&2
		;;
	esac
}

colima_runtime_fill_start_args() {
	local repo="$1"
	local mount
	COLIMA_START_ARGS=(
		start
		--runtime docker
		--cpus "$(colima_runtime_default_cpus)"
		--memory "$(colima_runtime_default_memory)"
		--disk "${COLIMA_DISK:-60}"
	)
	while IFS= read -r mount; do
		[[ -n "$mount" ]] || continue
		COLIMA_START_ARGS+=(--mount "$mount")
	done <<EOF
$(colima_runtime_mount_lines "$HOME" "$repo")
EOF
}

colima_runtime_up() {
	local platform repo
	platform="$(colima_runtime_platform)"
	case "$platform" in
	windows)
		echo "Run this inside Ubuntu on WSL2, not from PowerShell, cmd, or Git Bash." >&2
		echo "Then open the folder with Cursor or VS Code Remote - WSL." >&2
		return 1
		;;
	unsupported)
		echo "Colima setup supports macOS, Linux, and Windows WSL2." >&2
		return 1
		;;
	esac
	local reason
	if reason="$(colima_runtime_skip_reason)"; then
		echo "Skipping Colima: $reason"
		return 0
	fi
	repo="$(colima_runtime_root)"
	if [[ "$platform" == "wsl" ]]; then
		colima_runtime_warn_wsl_mount "$repo"
	fi
	colima_runtime_fill_start_args "$repo"
	if [[ -n "${COLIMA_DRY_RUN:-}" ]]; then
		printf 'colima'
		local arg
		for arg in "${COLIMA_START_ARGS[@]}"; do
			printf ' %q' "$arg"
		done
		printf '\n'
		return 0
	fi
	colima_runtime_install "$platform"
	colima_runtime_install_compose_wrapper
	colima_runtime_prepare_kvm "$platform"
	if command -v colima >/dev/null 2>&1 && colima status >/dev/null 2>&1; then
		echo "Colima is already running."
	else
		colima "${COLIMA_START_ARGS[@]}"
	fi
	if [[ "$(docker context show 2>/dev/null || true)" != "colima" ]]; then
		docker context use colima
	fi
	docker info >/dev/null
	echo "Colima Docker is ready (context: $(docker context show))."
}

colima_runtime_status() {
	local platform
	platform="$(colima_runtime_platform)"
	echo "platform: $platform"
	if ! command -v colima >/dev/null 2>&1; then
		echo "colima: not installed"
		return 1
	fi
	colima status || true
	docker context show 2>/dev/null || true
}

colima_runtime_main() {
	local command_name="${1:-up}"
	case "$command_name" in
	up) colima_runtime_up ;;
	status) colima_runtime_status ;;
	-h | --help | help)
		echo "Usage: bash scripts/colima-runtime.sh [up|status]"
		;;
	*)
		echo "Unknown command: $command_name" >&2
		echo "Usage: bash scripts/colima-runtime.sh [up|status]" >&2
		return 1
		;;
	esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
	colima_runtime_main "$@"
fi
