# Installing Cohenix Pilot on Windows

## What you get

1. A normal Windows installer: **Cohenix-Pilot-Setup.exe**
2. A desktop app that guides first-run setup
3. An isolated WSL2 distro named **Cohenix-Pilot** (Ubuntu 24.04)
4. Native Frappe Pilot + a Frappe v16 site (default profile: **hr**)

Docker Desktop / Docker Engine are **not** required and are **not** installed.

## Requirements

- Windows 11 x64 (preferred)
- Administrator approval when enabling WSL / Virtual Machine Platform
- Roughly 16 GB RAM recommended; 20+ GB free disk for a full HR stack
- Network access to GitHub (Pilot release, Frappe apps)
- WebView2 (bundled/online bootstrapper used if missing)

## Install steps

1. Download `Cohenix-Pilot-Setup.exe` and its `.sha256` checksum from the release
   or CI artifact. Verify the checksum before running.
2. Run the installer. Default install location is under
   `%LOCALAPPDATA%\Programs\Cohenix Pilot`.
3. Launch **Cohenix Pilot**.
4. Complete the first-run wizard:
   - Preflight checks
   - Enable WSL2 if needed (restart Windows when prompted; the wizard resumes)
   - Create the `Cohenix-Pilot` distro
   - Install Linux dependencies and Pilot
   - Choose an app profile (default **hr**)
   - Create `cohenix.localhost` and verify health
5. Open **Pilot Admin** or **Frappe Desk** from the Home screen.

## Credentials

The wizard generates strong passwords for:

- Pilot Admin UI
- Frappe Administrator
- MariaDB root

They are stored in the Windows credential store, not in the repository and not
in log files. Use **Settings → Reveal credentials** (requires confirmation) or
reset via Pilot Admin / documented recovery steps.

Do **not** expect the Docker sample passwords (`admin` / `123`).

## After install

| Action | Where |
|---|---|
| Start / Stop / Restart stack | Home |
| Open Pilot Admin | Home (default browser, loopback) |
| Open Frappe Desk | Home → `http://cohenix.localhost:8000` |
| Change profile / add site | Environments |
| Logs / diagnostics | Logs |
| Distro name, ports, editor | Settings |

## Uninstall

Removing the Windows application **keeps** the WSL distro and all site data.
To delete data, use **Settings → Remove Cohenix data** (explicit confirmation).
That flow may unregister the distro only after backup guidance and typed
confirmation. Ordinary uninstall never runs `wsl --unregister`.
