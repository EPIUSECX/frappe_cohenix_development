# Cohenix Frappe v16 development environment

This repository is the standard development platform for Cohenix Frappe
developers, CI jobs, GitHub Codespaces, Cursor cloud agents, and other
coding agents.

It is maintained by Cohenix, part of the EPI-USE group. Contact:
christiaan.swart@epiuse.com

## New developer path

You need Git, Docker, and VS Code (or Cursor) with the Dev Containers
extension. You do **not** need a local Python or Node install, and you do
**not** need to edit `/etc/hosts` for the default site.

```bash
git clone https://github.com/EPIUSECX/frappe_cohenix_development.git
cd frappe_cohenix_development
```

Open the folder in VS Code or Cursor and choose **Reopen in Container**.

When the container is ready:

```bash
devctl sync
devctl doctor
```

The default site is [http://cohenix.localhost:8000/app](http://cohenix.localhost:8000/app).
Administrator password: `admin`.

That is the whole happy path. `devctl` talks to Pilot, Bench, MariaDB, and
Redis for you.

## Performance

The main win is **not compiling the toolchain on a developer machine**.

| What | Previous bootstrap | Cohenix v16 platform |
|---|---|---|
| Python | pyenv compiled 3.10 **and** 3.14 on every image rebuild | uv installs prebuilt CPython **3.14.2** (~1s at image build) |
| Node | nvm installed 16 **and** 24 | Official **24.12.0** tarball, SHA256-checked |
| Image rebuild | Local compile of two Pythons and two Nodes | Pull `ghcr.io/epiusecx/cohenix-frappe-dev:v16` (`pull_policy: missing`) |
| Image size | Two runtimes per language | **1.47 GiB** (measured amd64, 1,539,801,676 bytes) |
| Fresh `devctl sync` (hr profile, two sites, ERPNext + HRMS) | After the image compile, then installer.py | **328s** in GitHub Actions image smoke (`241c9fb`) |
| Repeat `devctl sync` with no config change | Re-ran installer work | **0s** (`nothing to do`, fingerprint match) |
| Container restart | Could reinstall | Named volumes persist; `devctl start` only |

CI writes `docs/last-smoke-metrics.txt` (`FRESH_SECONDS` / `REPEAT_SECONDS`) on
each image workflow run. Those two numbers are measured. The old pyenv compile
was not re-timed in this repository; a typical CPython pyenv build is several
minutes **per version**, and the previous Dockerfile built two Pythons and two
Nodes. That cost is gone from the daily loop.

## Watching progress

`devctl sync` and `devctl start` are still non-interactive (CI and coding
agents never get a prompt). They now **sell the current stage** on the terminal:

1. A header with profile, Python, Node, Pilot, bench, sites, and apps.
2. Numbered banners `>>> [3/10] Initialize bench` around each step, including
   Pilot's own `[1/12]` bars.
3. A heartbeat every 15 seconds while a stage is still running, so a quiet
   `pilot init` or site create is not a black box.
4. `<<< [3/10] Initialize bench  done (56s)` when the step finishes, or
   `skipped` when the fingerprint says it is unnecessary.
5. A timing table at the end.

On GitHub Actions the same stages become collapsible `::group::` log sections
(the Compose service receives `GITHUB_ACTIONS`). There is no `input()`, no
spinner that fights Pilot's output, and no TTY requirement.

## Cloud agents and CI

```bash
devcontainer up --workspace-folder .
devcontainer exec --workspace-folder . devctl sync
devcontainer exec --workspace-folder . devctl verify
```

Or with Compose directly:

```bash
docker compose -f .devcontainer/docker-compose.yml up -d --build
docker compose -f .devcontainer/docker-compose.yml exec frappe devctl sync
docker compose -f .devcontainer/docker-compose.yml exec frappe devctl doctor
```

No Docker Desktop UI, no interactive installer, no host Python/Node, and no
`/etc/hosts` change for `*.localhost` names.

## What you get

Three layers:

1. **Cohenix development image** — `ghcr.io/epiusecx/cohenix-frappe-dev:v16`
   with Python 3.14, Node 24, Yarn, uv, Bench, Redis server, MariaDB client,
   and PDF libraries. Developers pull this image; they do not compile Python.
2. **Dev Container / Compose** — MariaDB 11.8, the Frappe container, optional
   Mailpit/Postgres/UI-test profiles, named volumes for Pilot and caches.
3. **`devctl`** — environment setup, health, apps, sites, recovery, diagnostics.

Versions live in `toolchain.toml`. The image, Compose file, CI, and `devctl`
all read from it.

## Common commands

| Command | Purpose |
|---|---|
| `devctl sync` | Create or update the bench, apps, and sites. Safe to re-run. |
| `devctl doctor` | Diagnose the stack and print fixes for failures. |
| `devctl verify` | Fail if the provisioned environment is incomplete. |
| `devctl status` | Short health view. |
| `devctl start` / `stop` / `restart` | Pilot process set (web, workers, Socket.IO, Redis, scheduler). |
| `devctl site create second.localhost` | Extra site on the same HTTP port (Host routing). |
| `devctl site reset cohenix.localhost --yes` | Drop one site. |
| `devctl app add https://github.com/org/app --branch version-16` | Add an app overlay. |
| `devctl app remove hrms` | Remove an overlay app. |
| `devctl profile use hr` | Select an application set. |
| `devctl reset --caches --yes` | Drop uv/yarn/npm/asset caches. |
| `devctl reset --bench --yes` | Drop env/sites/config; keep app checkouts. |
| `devctl reset --all --yes` | Drop all benches under `PILOT_DIR`. Never deletes this git repo. |

`python installer.py` still works and calls `devctl sync`. Prefer `devctl`.

Classic Bench commands still work after `cd development-bench`. `bench start`
is shimmed to Pilot. Prefer `devctl start`.

## Profiles

Application sets are declared in `config/profiles.toml`. Repositories are
real Frappe/EPIUSECX URLs, not invented names.

| Profile | Apps |
|---|---|
| `frappe` | frappe |
| `erp` | frappe, erpnext |
| `hr` | frappe, erpnext, hrms (**default**) |
| `localisation` | hr + `za_local_core`, `za_local` (`cohenix_local_za`), `za_local_payroll` |
| `integrations` | erp + payments + ecommerce_integrations |
| `full-cohenix` | localisation + payments + ecommerce_integrations |

```bash
devctl profile use hr
devctl sync
devctl profile use localisation
devctl sync
```

Project-specific apps: set `COHENIX_APPS_JSON=/path/to/apps.json` (frappe_docker
shape) or `devctl app add <repository>`. Local overlay: `.cohenix/apps.overlay.toml`.

## Recovery

`devctl sync` repairs safe, incomplete state:

- half-created Python environments
- `pilot new` without `pilot init`
- missing Redis config
- missing `assets.json`
- sites that exist but are missing apps
- shallow Pilot clones

Destructive recovery is explicit:

```bash
devctl site reset <site> --yes
devctl reset --caches --yes
devctl reset --bench --yes
devctl reset --all --yes
```

Non-interactive sessions require `--yes`. CI never prompts.

## Updating Pilot

The pinned release is `toolchain.toml` → `[pilot].version`. It is **not**
`latest`.

1. Put the candidate tag in `[pilot].canary_version` (and its SHA256).
2. Wait for `.github/workflows/pilot-canary.yml` (Monday schedule or
   workflow_dispatch).
3. If the canary smoke test passes, bump `[pilot].version` and `sha256` in a
   reviewable commit. Do not auto-promote.

## Updating runtime versions

Edit `toolchain.toml`, then:

1. Keep Dockerfile ARG defaults, `.devcontainer/.env.example`, and Compose
   defaults in agreement (unit tests check this).
2. Rebuild and publish the image (see below).
3. Rebuild Dev Containers so they pull the new tag.

Python 3.14 and Node 24 are required for Frappe v16. Do not add Python 3.10
or Node 16 to this image. Legacy runtimes belong on `version-15_cohenix`.

## Publishing a development image

```bash
python scripts/export_toolchain.py
docker build -f images/v16/Dockerfile -t ghcr.io/epiusecx/cohenix-frappe-dev:v16 .
```

CI (`.github/workflows/image.yml`) builds the image, runs the environment
smoke test (real site, ERPNext, Frappe HR, HTTP, Socket.IO, restart,
idempotent sync), and **only then** publishes `linux/amd64` and `linux/arm64`
to GHCR from `version-16_cohenix`.

Local image work:

```bash
docker compose -f .devcontainer/docker-compose.yml build frappe
```

`pull_policy: missing` uses a local build when GHCR does not have the tag yet.

## Compose profiles

Default stack: `mariadb` + `frappe`.

```bash
docker compose -f .devcontainer/docker-compose.yml --profile mail up -d
docker compose -f .devcontainer/docker-compose.yml --profile postgres up -d
docker compose -f .devcontainer/docker-compose.yml --profile ui-tests up -d
docker compose -f .devcontainer/docker-compose.yml --profile legacy-redis up -d
```

MariaDB and Redis are not published on the host. Frappe HTTP/realtime ports
are forwarded by the Dev Container, not `ports:` in Compose, so several
environments can run without collisions.

## URLs and passwords

| What | Where |
|---|---|
| Site | http://cohenix.localhost:8000/app |
| Pilot admin | http://localhost:8002 |
| Mailpit (profile `mail`) | http://localhost:8025 |
| Site Administrator | `admin` / `ADMIN_PASSWORD` |
| MariaDB root | `123` / `DB_ROOT_PASSWORD` |

These are development credentials. Do not use them in production. SSH keys
are not mounted by default; use GitHub credential forwarding.

## Architecture notes

- Benches live at `/home/frappe/pilot/benches/<name>` on a Docker volume.
  `/workspace/development-bench` is a symlink so app code stays editable.
- Source for **this** repository is the `/workspace` bind mount.
- uv, Yarn, and npm caches are named volumes and survive container rebuilds.
- MariaDB data is a named volume and survives container replacement.
- Sites use `.localhost` names so Host routing works without `/etc/hosts`.

See [docs/MIGRATION.md](docs/MIGRATION.md) if you are coming from the previous
installer-based container, and [docs/TECHNICAL_REPORT.md](docs/TECHNICAL_REPORT.md)
for the redesign notes and Pilot limitations.
