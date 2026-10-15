# Support, recovery, and troubleshooting

## Diagnostic report

**Logs → Copy diagnostic report** produces a redacted text blob:

- Windows build, WSL version, distro list (names only)
- Install stage + last error code
- Port probe results
- Pilot / Frappe health booleans
- **No** passwords, tokens, or site encryption keys

Attach that report when asking for help.

## Common failures

| Symptom | Likely cause | Remediation |
|---|---|---|
| Wizard asks to restart | WSL features just enabled | Restart Windows; reopen Cohenix Pilot |
| Distro create fails | Existing name / corrupt import | Choose a new name or opt in to repair; never force-unregister silently |
| Ports in use | Another bench or app on 8000/8002/9000 | Change ports in Settings or stop the other process |
| Site not reachable from Windows | WSL not running / bind issue | Start from Home; confirm `wsl -d Cohenix-Pilot` works |
| Pilot Admin 401 | Session expired | Open Admin via the app (issues a fresh link when possible) |
| Provision fails mid-way | Network / git / MariaDB | Retry the stage; fingerprint/idempotent scripts skip completed work |
| "Docker required" message | None from this app | Confirm you launched Cohenix Pilot, not an old Docker guide |

## Recovery

1. **Retry stage** — Home / Logs retry continues from the persisted stage.
2. **Repair Linux deps** — Settings → Repair (re-runs idempotent package scripts).
3. **Restart services** — Home → Restart (Pilot stop/start only).
4. **Site backup** — Before migrations or reset, use Pilot Admin backups or
   `scripts/native-wsl/backup-site.sh`.
5. **Reset bench (destructive)** — Requires typing the bench name; backs up
   first when MariaDB is reachable.
6. **Remove distro (destructive)** — Settings only; never part of app uninstall.

## WSL resources

`%UserProfile%\.wslconfig` applies to **all** WSL2 distributions. Cohenix Pilot
may **suggest** memory/CPU limits but will not write that file without an
explicit Settings action and a clear warning.

## Updates

- **Windows app**: manual check in Settings (update channel).
- **Frappe / apps**: never auto-upgraded on launch. Use Pilot Admin or an
  explicit "Update stack" action that backs up first.
