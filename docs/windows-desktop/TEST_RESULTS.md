# Test results — Cohenix Pilot for Windows

Recorded during the initial implementation branch. Update this file when CI or
lab results change.

## Automated (this environment / CI)

| Suite | Host | Result | Notes |
|---|---|---|---|
| `tests/` existing unit tests | Linux | **Passed** (PR CI + local) | Docker path unchanged |
| `tests/windows_desktop/` | Linux | **Passed** | Profile resolve + native Pilot pin |
| `desktop/cohenix-pilot` vitest | Linux | **Passed** | Profile allowlist |
| Frontend production build | Linux | **Passed** | `npm run build` |
| `src-tauri` cargo test | Linux | **Passed** (9 tests) | Validation, state machine, redact |
| Cohenix Pilot Windows workflow | `windows-latest` | **Passed** | Run [38731018602](https://github.com/EPIUSECX/frappe_cohenix_development/actions/runs/38731018602) |
| NSIS `Cohenix-Pilot-Setup.exe` | `windows-latest` GHA | **Built** | Artifact `Cohenix-Pilot-Setup` (~1.8 MiB); SHA-256 `68ce64325d3fb8dcb68506a310cb19dcb8ea8564b1ca570175b157308b7bf28c`; version `0.1.0`; **unsigned** |
| Development image / existing CI | GHA | **Passed** | No Docker-path regression on this branch |

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
