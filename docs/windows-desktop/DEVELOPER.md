# Developer setup — Cohenix Pilot (Windows)

## Prerequisites

- Windows 11 x64 (Windows 10 only if verified separately)
- Node.js 22+ and Rust stable (for local Tauri builds)
- WebView2 Runtime (usually preinstalled on Windows 11)
- Git

Linux/macOS contributors can edit UI and scripts, run unit tests, and review
docs. Producing `Cohenix-Pilot-Setup.exe` requires a Windows host or the
`cohenix-pilot-windows` GitHub Actions workflow.

## Layout

| Path | Role |
|---|---|
| `desktop/cohenix-pilot/` | Tauri 2 + React/TypeScript app |
| `desktop/cohenix-pilot/src-tauri/` | Rust host: WSL IPC, state, validation |
| `scripts/windows/` | PowerShell prereq / WSL helpers |
| `scripts/native-wsl/` | Ubuntu provisioner (no Docker) |
| `docs/windows-desktop/` | Architecture, support, release |
| `config/profiles.toml` | App profiles (shared with Docker path) |
| `toolchain.toml` `[pilot.native_wsl]` | Native Pilot pin + checksum |

## Local UI development (any OS)

```bash
cd desktop/cohenix-pilot
npm install
npm run dev
```

Without Windows, Rust commands that call `wsl.exe` return structured errors; the
UI can still be exercised with mocked IPC in tests.

## Local Windows build

```powershell
cd desktop\cohenix-pilot
npm install
npm run tauri build
```

NSIS output (product name configured as Cohenix Pilot):

`src-tauri/target/release/bundle/nsis/Cohenix-Pilot_*_x64-setup.exe`

Rename/publish as `Cohenix-Pilot-Setup.exe` in CI (see release docs).

## Native WSL scripts (inside Ubuntu)

```bash
# From the Cohenix repo checkout inside the distro:
bash scripts/native-wsl/provision.sh --profile hr --stage all
bash scripts/native-wsl/health.sh
bash scripts/native-wsl/lifecycle.sh status
```

## Tests

```bash
# Shared Python unit tests (Linux CI)
python -m unittest discover -s tests -p 'test*.py' -v

# Desktop-specific Python tests
python -m unittest discover -s tests/windows_desktop -p 'test*.py' -v

# Frontend
cd desktop/cohenix-pilot && npm test

# Rust (on Windows runner or with appropriate targets)
cd desktop/cohenix-pilot/src-tauri && cargo test
```

## Do not break Docker

Never change `.devcontainer/`, `cohenix_dev/` container assumptions, or the
default `[pilot] version` pin unless intentionally versioning the image path.
Native WSL pins live only under `[pilot.native_wsl]`.
