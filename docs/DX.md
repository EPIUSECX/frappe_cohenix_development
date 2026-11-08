# Developer experience notes

This document records how the Cohenix platform compares to public Frappe
tooling, what we already do better, and what was added (or left open) to keep
setup fast and daily work pleasant.

## How setup works (end to end)

1. **Image** (`images/v16/Dockerfile`) — prebuilt Python 3.14, Node 24, Yarn,
   uv, Bench, redis-server, `devctl`. Developers pull
   `ghcr.io/epiusecx/cohenix-frappe-dev:v16`; they do not compile pyenv/nvm.
2. **Compose / Dev Container** — MariaDB 11.8 + Frappe container, named volumes
   for Pilot and package caches. Optional profiles: `mail`, `postgres`,
   `ui-tests`, `legacy-redis`.
3. **Lifecycle hooks**
   - `onCreate` → volume ownership
   - `updateContent` → editable `devctl` + optional pre-commit (Codespaces prebuilds)
   - `postCreate` → MariaDB wait, `devctl sync`
   - `postStart` → sync (fingerprint no-op when unchanged), `devctl start`,
     `devctl wait`, `devctl doctor`, `devctl urls`
4. **`devctl sync`** — install Pilot, init bench, create `cohenix.localhost`,
   install profile apps, build assets, fingerprint. Repeat sync is **0s** when
   nothing changed.

## Versus public Frappe repos

| Area | Upstream (`frappe_docker` / classic bench) | This platform |
|---|---|---|
| First open | Copy `devcontainer-example`, reopen, run interactive `installer.py`, then `bench start` | Reopen in Container; wait for postStart; site is up |
| Toolchain | `frappe/bench` image still compiles extra Python/Node generations | Prebuilt CPython + Node tarball, pinned in `toolchain.toml` |
| Process manager | Classic `bench start` / Honcho | Pilot + Cohenix scheduler/reload shims |
| App sets | Manual `get-app` / apps.json prompts | Declarative profiles in `config/profiles.toml` |
| Health | Manual checks | `devctl doctor` with fix guidance |
| Progress | Quiet long `bench init` | Numbered stages + 15s heartbeat + GHA groups |
| Debug | `development/vscode-example/launch.json` | `.vscode/launch.json` for Pilot bench paths |
| Cloud agents | Not first-class | `.cursor/environment.json` + install/start scripts |

Pilot's own `pilot dev setup` / `pilot dev start` is excellent for **single-app**
repositories (clone app → setup → start). This repository is the **shared
platform** for ERPNext/HR/localisation work: multi-app profiles, MariaDB in
Compose, and editor lifecycle. Keep both models; do not replace `devctl` with
`pilot dev` for the Cohenix default path.

## Added for easy daily use

- `devctl urls` — site, admin, Mailpit links
- `devctl logs` — follow `/tmp/pilot-*.log`
- `devctl console` — Frappe console on the default (or named) site
- `devctl wait` — HTTP `frappe.ping` readiness
- `devctl seed` — demo company + sample HR employees
- `devctl debug enable|disable|status` — attach debugpy on `:5678` without stopping Pilot
- Shell MOTD after sync (URLs + common commands)
- Mailpit auto-wiring when the `mail` Compose profile is up
- Profiles `crm` and `helpdesk` (public `version-16` branches)
- `config/apps-example.json` for `COHENIX_APPS_JSON`
- VS Code / Cursor debug launch configs (including Attach to Pilot web)
- Cursor Cloud Agent install/start scripts under `.cursor/`
- Codespaces prebuild-ready hooks + [CODESPACES.md](CODESPACES.md)
- Pilot compat re-audit (`scripts/audit-pilot-compat.py`); scheduler workaround dropped on canary

## Still worth doing later

1. **Faster cold sync** — optional `frappe`-only default for agents that do
   not need ERPNext/HR; or Pilot prebuilt assets when apps publish them.
2. **Repo-managed Cursor environment** — point a team environment at the
   committed `.cursor/environment.json` so Cloud Agents share install/start.
3. **Digest-pin MariaDB** after a stable week on 11.8.9.
4. **Drop more Pilot workarounds** as upstream closes Redis-external,
   `assets.json`, and mariadb login-scope gaps (`python scripts/audit-pilot-compat.py`).

## Quick reference

```bash
devctl doctor          # health + fix hints
devctl urls            # open these in the browser
devctl logs            # why did web not come up?
devctl console         # REPL with Frappe imported
devctl seed            # demo HR company + employees
devctl debug enable    # attach on :5678 without stopping Pilot
devctl profile use crm # then: devctl sync
devctl app add https://github.com/org/app --branch version-16
```

Site: http://cohenix.localhost:8000/app — Administrator / `admin`.
