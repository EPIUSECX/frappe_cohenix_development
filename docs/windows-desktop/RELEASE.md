# Release procedure — Cohenix-Pilot-Setup.exe

## Versioning

Mirror the desktop package version in:

- `desktop/cohenix-pilot/package.json`
- `desktop/cohenix-pilot/src-tauri/tauri.conf.json` (`version`)
- Git tag optional: `cohenix-pilot-vX.Y.Z`

## CI artifact (unsigned test builds)

Workflow: `.github/workflows/cohenix-pilot-windows.yml`

On `windows-latest` it:

1. Installs Node + Rust
2. Runs frontend/unit tests
3. Builds the Tauri NSIS bundle
4. Renames the setup exe to `Cohenix-Pilot-Setup.exe`
5. Writes `Cohenix-Pilot-Setup.exe.sha256`
6. Uploads both as workflow artifacts

**Unsigned builds are not code-signed.** Do not describe them as signed.

## Production code signing (manual)

1. Obtain an Authenticode certificate (EV recommended for SmartScreen).
2. Configure Tauri bundler `certificateThumbprint` / Azure Trusted Signing as
   documented at https://v2.tauri.app/distribute/windows-installer/
3. Store secrets in GitHub Environments; never commit `.pfx` files.
4. Sign `Cohenix-Pilot-Setup.exe`, then re-hash SHA-256 after signing.
5. Publish checksum + version notes + AGPL source-offer URL for Pilot if the
   installer redistributes the tarball.

## Smoke checklist (Windows 11 lab)

Mark each only when actually executed:

- [ ] Clean VM, no WSL — guided enable + restart resume
- [ ] Existing unrelated Ubuntu distro untouched
- [ ] Fresh install: Pilot Admin, Frappe v16, ERPNext, HRMS, login
- [ ] Stop/start, app restart, Windows reboot — data persists
- [ ] Re-provision — no duplicate bench/site / credential overwrite
- [ ] Forced stage failure — recovery + logs, no silent success
- [ ] Docker Desktop/Engine not required
- [ ] Localhost routing + Admin auth from Windows

Until a lab run is recorded, treat Windows E2E as **not verified**.
