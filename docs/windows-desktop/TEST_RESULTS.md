# Test results — Cohenix Pilot for Windows

Recorded during the initial implementation branch. Update this file when CI or
lab results change.

## Automated (this environment / CI)

| Suite | Host | Result | Notes |
|---|---|---|---|
| `tests/` existing unit tests | Linux | Run in PR CI | Must stay green (Docker path) |
| `tests/windows_desktop/` | Linux | Implemented | Profile resolve + native Pilot pin |
| `desktop/cohenix-pilot` vitest | Linux | Implemented | Profile allowlist |
| `src-tauri` cargo test | Linux CI | Workflow installs WebKit deps | Validation, state machine, redact |
| NSIS `Cohenix-Pilot-Setup.exe` | `windows-latest` GHA | Workflow added | Artifact + SHA-256; **unsigned** |

## Real Windows 11 + WSL2 smoke (required for compatibility claim)

| # | Scenario | Status |
|---|---|---|
| 1 | Clean Windows, no WSL — guided enable + restart resume | **Not run** |
| 2 | Existing unrelated Ubuntu distro untouched | **Not run** |
| 3 | Fresh install: Admin, Frappe v16, ERPNext, HRMS, login | **Not run** |
| 4 | Stop/start, app restart, Windows reboot persistence | **Not run** |
| 5 | Re-provision without duplicate bench/site | **Not run** |
| 6 | Forced stage failure → recovery, no silent success | **Not run** |
| 7 | Docker Desktop/Engine not required | **Not run** (design: no Docker calls) |
| 8 | Localhost routing + Admin auth from Windows | **Not run** |

**Verdict:** Source, scripts, UI, unit tests, and Windows CI packaging are in
place. **Do not claim full Windows compatibility until the smoke table above is
executed on a real Windows 11 x64 machine or runner with WSL2.**
