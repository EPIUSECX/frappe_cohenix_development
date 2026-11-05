# Cohenix Pilot for Windows — Architecture

## Goal

Cohenix Pilot is a Windows 11 x64 desktop application that installs and manages a
local Frappe v16 development environment **without Docker Desktop or Docker
Engine**. The Frappe stack runs natively inside an isolated Ubuntu 24.04 WSL2
distribution. The Windows app is the control plane; Linux is the runtime.

This path is **additive**. The existing Docker / Dev Container / `devctl` workflow
remains the primary path for Linux, CI, and Codespaces. Native WSL code lives
under `desktop/`, `scripts/windows/`, and `scripts/native-wsl/` and must not
change container behaviour.

## Boundaries

```text
┌─────────────────────────────────────────────────────────────┐
│  Windows 11                                                  │
│  ┌──────────────────────┐    typed IPC (allowlisted)         │
│  │ Cohenix Pilot (Tauri)│─────────────────────────────────┐  │
│  │ React UI + Rust host │                                 │  │
│  └──────────────────────┘                                 │  │
│           │ wsl.exe -d Cohenix-Pilot -- …                 │  │
│           ▼                                               │  │
│  ┌──────────────────────────────────────────────────────┐ │  │
│  │ WSL2 VM (shared by all distros)                        │ │  │
│  │  ┌──────────────────────────────────────────────────┐│ │  │
│  │  │ Distro: Cohenix-Pilot (Ubuntu 24.04 rootfs)      ││ │  │
│  │  │  MariaDB · Redis · Node · Python/uv · Pilot CLI  ││ │  │
│  │  │  ~/pilot/benches/development-bench               ││ │  │
│  │  │  Frappe site: cohenix.localhost                  ││ │  │
│  │  └──────────────────────────────────────────────────┘│ │  │
│  └──────────────────────────────────────────────────────┘ │  │
│  localhost:8000 (Desk) · :8002 (Pilot Admin) · :9000      │  │
└─────────────────────────────────────────────────────────────┘
```

## Why not reuse `devctl` as-is?

`devctl` assumes:

- A prebuilt Cohenix image with Python/Node/uv already installed
- MariaDB as a **Compose sidecar** (`db_host=mariadb`), not a local daemon
- Pilot installed from a pinned tarball **without** `install.sh` (to avoid
  system MariaDB/nginx/supervisor that would conflict with the container path)
- Workspace paths under `/workspace` and Docker volumes

Native WSL needs local MariaDB/Redis, Ubuntu package setup, WSL networking, and
a dedicated distro lifecycle. The native provisioner is therefore a separate
adapter that still reads `config/profiles.toml` and compatible pins from
`toolchain.toml`.

## Version pins

| Component | Docker / Dev Container | Native WSL (this app) |
|---|---|---|
| Frappe | `version-16` | `version-16` (same) |
| Default profile | `hr` | `hr` (same) |
| Python (bench) | 3.14.2 via uv | 3.14.2 via uv (Pilot/uv) |
| Node | 24.12.0 | 24.12.0 (official tarball) |
| Pilot | `v0.0.23-pre-alpha` | `v0.0.64-pre-alpha` (see below) |
| MariaDB | Compose `11.8.9` | Host MariaDB 11.8 (Pilot installer family) |
| Site / ports | `cohenix.localhost:8000/9000/8002` | same defaults |

### Why a different Pilot pin?

The container path pins `v0.0.23-pre-alpha` for reproducibility inside the
Cohenix image. Current upstream Pilot (Ubuntu 24.04+ installer, Admin API, CLI
flags such as `pilot new --admin-password`, non-interactive `init`) has moved
forward. Native WSL therefore pins **`v0.0.64-pre-alpha`** with an explicit
SHA-256 in `toolchain.toml` under `[pilot.native_wsl]`. That pin is independent
of the Docker image pin and is never auto-upgraded on app launch.

## Security model

- Tauri IPC exposes **typed, allowlisted** commands only (no arbitrary shell).
- Distro name, bench name, site name, profile id, ports, and URLs are validated
  before any `wsl.exe` invocation.
- Secrets (Admin UI password, site Administrator password, MariaDB root) are
  generated with a CSPRNG, stored in the Windows credential store
  (`windows-credentials` / DPAPI-backed), and never logged or put in URLs.
- Sample Docker passwords (`admin` / `123`) are **not** used on the native path.
- Management endpoints bind to loopback by default.
- Uninstall of the Windows app does **not** run `wsl --unregister`. Data removal
  is a separate, confirmed action.

## First-run state machine

Persisted under `%LOCALAPPDATA%\CohenixPilot\state.json`:

1. `preflight` → OS, arch, virtualization, WSL, RAM, disk, WebView2, ports
2. `wsl_enable` → documented `wsl.exe` enablement; optional restart; resume
3. `distro` → import/create `Cohenix-Pilot` (never overwrite without opt-in)
4. `linux_deps` → packages, Node, uv, MariaDB, Redis
5. `pilot_install` → pinned tarball + checksum
6. `cohenix_provision` → profile → bench.toml → init → site → start
7. `verify` → WSL, services, Admin `/health`, Frappe HTTP, apps
8. `ready`

Every stage is idempotent. Reopening the app detects an existing install and
skips destructive work.

## Upstream Pilot AGPL-3.0

Frappe Pilot is AGPL-3.0. Cohenix Pilot **orchestrates** a user-installed Pilot
release inside WSL; it does not vendor Pilot source into the Windows binary by
default. Redistributing modified Pilot code, or a combined work that includes
Pilot, triggers AGPL obligations (source offer, corresponding source for network
use of modified versions). See `docs/windows-desktop/LICENSING.md`.

## Known risks

- WSL2 is a lightweight VM (memory/CPU overhead). `%UserProfile%\.wslconfig`
  affects **all** distros; the app never edits it silently.
- Closing the desktop app may leave WSL processes running; Start/Stop must talk
  to Pilot explicitly, and a keepalive may be required so the distro does not
  idle-exit.
- Windows ↔ WSL localhost forwarding differs across WSL versions; verification
  must probe from Windows.
- Cross-compiling the NSIS installer from Linux is unsupported here; Windows CI
  produces `Cohenix-Pilot-Setup.exe`.
- Full E2E smoke on clean Windows VMs requires a Windows 11 runner or manual lab.
