# Migration from the previous Cohenix development container

This branch replaces `installer.py` as the daily driver with `devctl`, moves
the toolchain into a prebuilt image, and switches the default database to
MariaDB 11.8.

## Docker Desktop to Colima

Local development uses Colima on macOS, Linux, and Windows WSL2. From the
repository root:

```bash
bash scripts/colima-runtime.sh up
```

Quit Docker Desktop so it does not keep the same ports. The script points
the Docker client at the `colima` context and installs a Compose plugin
that lets VS Code read its generated Dockerfile under Buildx 0.37.2 and
later. On Windows, run that command inside Ubuntu on WSL2 and open the
folder with Remote - WSL. Details are in the README.

## What you should do on an existing machine

1. Commit or stash work in any app checkouts you care about. Default app
   checkouts lived under `pilot/benches/development-bench/apps/` on the bind
   mount. They now live on the `cohenix-pilot` Docker volume, still linked
   from `/workspace/development-bench`.
2. Rebuild the Dev Container (not just restart). The image is no longer
   compiled on your laptop from `resources/Dockerfile`. **Reopen in
   Container** then runs `devctl sync`, `devctl start`, and `devctl doctor`
   for you. You do not need to type them unless you skipped autosync.

You can keep using `python installer.py`; it calls `devctl sync`.

## Behaviour that stays

- Pilot still manages the bench. Classic Bench is not the process manager.
- Default apps are still Frappe, ERPNext, and Frappe HR on `version-16`.
- Default site is still `cohenix.localhost`.
- Incomplete venv / half-created site / missing `assets.json` recovery remains.
- MariaDB user host grants are still repaired to `%`.
- `bench start` is still shimmed to Pilot. The shim now also reloads Pilot
  workers after `bench --site … install-app` (and other mutating commands)
  so Desk does not AJAX-error until a full Pilot stop/start.

## Behaviour that changes

| Old | New |
|---|---|
| Image built locally from `resources/Dockerfile` | Pull `ghcr.io/epiusecx/cohenix-frappe-dev:v16` (or build `images/v16/Dockerfile`) |
| Python 3.14 **and** 3.10, Node 24 **and** 16 compiled with pyenv/nvm | Python 3.14.2 and Node 24.12.0 only, installed from official binaries |
| MariaDB 10.6 + `skip-innodb-read-only-compressed` | MariaDB 11.8.9, no 10.6 flag |
| Pilot data on the `/workspace` bind mount | Pilot data on volume `/home/frappe/pilot` |
| Compose published 8000-8005 and 9000-9005 on the host | Dev Container port forwarding |
| Mailpit always started | Compose profile `mail` |
| `python installer.py` | `devctl sync` |
| `PILOT_DIR=/workspace/pilot` | `PILOT_DIR=/home/frappe/pilot` |

## If you need the old v15 / Python 3.10 image

Use the `version-15_cohenix` branch. Do not add those runtimes back to the
v16 image.

## Environment variables

Copy `.devcontainer/.env.example` to `.devcontainer/.env` only when you need
overrides. Leave `PILOT_VERSION` unset, or set it to `latest`, so `devctl sync`
installs the newest Pilot release. An explicit tag freezes that release.
