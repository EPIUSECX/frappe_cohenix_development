# Cohenix Frappe v16 development platform — technical report

## What changed

The repository is no longer a bootstrap script around Frappe and Pilot. It is
a three-layer development platform.

### Layer 1 — Cohenix development image

- Canonical Dockerfile: `images/v16/Dockerfile`.
- Published name: `ghcr.io/epiusecx/cohenix-frappe-dev:v16`.
- Python **3.14.2** via uv’s prebuilt CPython (no pyenv compile).
- Node **24.12.0** from nodejs.org with SHA256 verification (no nvm, no Node 16).
- Yarn **1.22.22**, uv **0.11.33**, Bench **v5.31.0**, redis-server, MariaDB client.
- wkhtmltopdf 0.12.6.1-3 checksum-verified per architecture.
- `devctl` is installed in the image; `/workspace` is installed editable at
  container create so platform work is live.

Why not `FROM frappe/bench:v5.31.0`?

- Upstream tags still compile extra Python/Node generations.
- Upstream uses unpinned `git clone --depth 1` pyenv and `frappe/bench:latest`
  in the Dev Container example.
- Upstream does not ship redis-server, which Pilot requires.
- Upstream does not pin uv.

Those incompatibilities are documented here; the Cohenix Dockerfile stays
small and v16-only.

### Layer 2 — Dev Container / Compose

- MariaDB **11.8.9** with `MARIADB_AUTO_UPGRADE=1`. The MariaDB 10.6
  `--skip-innodb-read-only-compressed` flag is gone.
- Mailpit, Postgres, Cypress, and legacy Redis are Compose **profiles**.
- Named volumes: Pilot, uv cache, Yarn cache, npm cache, MariaDB data.
- Bind mount is only `/workspace` (this repository).
- Frappe HTTP/realtime ports are Dev Container `forwardPorts` with
  `portsAttributes`. MariaDB and Redis are not published on the host.

### Layer 3 — `devctl`

`cohenix_dev/` replaces the growing `installer.py` responsibilities.
`python installer.py` remains as a compatibility wrapper.

Commands: `sync`, `doctor`, `verify`, `status`, `start`, `stop`, `restart`,
`site create|reset`, `app add|remove`, `profile use|list`, `reset`.

Fingerprints live at
`/home/frappe/pilot/benches/<name>/.cohenix/fingerprint.json`.
`devctl sync` no-ops when the requested profile, toolchain, Pilot pin, apps,
and sites already match. Provenance remains in `.provisioning.json` (schema 2).

Profiles are `config/profiles.toml`. Repositories were taken from the previous
installer defaults and from public EPIUSECX/Frappe GitHub repositories. Names
such as `cohenix_erp` in the old README had no matching public repository and
were not invented here.

## What remains intentionally unchanged

- Pilot is still the bench manager. Classic Bench is not used as a replacement.
- Pinned Pilot release remains **v0.0.23-pre-alpha** until the canary workflow
  proves a newer tag. v0.0.55-pre-alpha is recorded as `canary_version` only.
- Every installer workaround that still applies on v0.0.23 (and, except
  top-level `packaging`, on v0.0.55) is kept. See `config/pilot-compat.toml`.
- Development passwords stay `admin` / `123` and are overridable.
- `.localhost` site names stay the default so `/etc/hosts` is not required.

## Current Pilot limitations (re-audited against v0.0.55-pre-alpha)

| Limitation | Status |
|---|---|
| CLI undeclared `packaging` dependency | Fixed in 0.0.55 via `pilot._vendor.packaging`; also hidden if `~/.local/bin/python3` is a venv symlink. `devctl` now execs `VIRTUAL_ENV/bin/python3` |
| CLI undeclared `pymysql` | Still required on pin and canary |
| No external Redis | Still required; image includes redis-server |
| `new-site` omits `--mariadb-user-host-login-scope` | Still repaired after create |
| `build_missing_assets` keys off symlink dirs, not `assets.json` | Still rebuilt by `devctl` |
| Release tarball clones apps `--depth 1` | Still deepened to 200 commits |
| `install.sh` wants host MariaDB/nginx/supervisor | Still avoided |
| `config/pids` missing for classic Bench | Still created |
| Admin UI default port 7000 | Still remapped to 8002 |
| Temporary Redis needed for `new-site` | Still started around site create |
| `frappe migrate` requires Redis | Extra migrate is skipped after create/install, otherwise Redis is started |
| Generated Procfile omits `frappe schedule` | `devctl start` adds it and starts the process |
| `VERSION=dev` would get full history; we will not lie about the version | Deepen workaround kept |

Do not set `PILOT_VERSION=latest` on the normal path.

## Test results

### Unit tests

Run with `python -m unittest discover -s tests -p 'test*.py' -v`.

Covered: Pilot release URLs and checksums, profiles, fingerprints, incomplete
venv recovery, CLI surface, toolchain agreement across Dockerfile/Compose/env,
SQL identifier guard, installer wrapper, Pilot workaround manifest, stage
progress reporter (banners, skip, heartbeat, GitHub Actions groups, sync wiring).

### Environment smoke tests

`tests/smoke/run-smoke.sh` (CI job in `.github/workflows/image.yml`):

- build/start the stack
- `devctl sync` with ERPNext + Frappe HR
- asset build (via sync)
- HTTP `frappe.ping`
- Socket.IO port
- Redis
- second site Host routing
- container restart + persistence
- second `devctl sync` (idempotency)
- `devctl doctor` / `devctl verify`

Publishing a GHCR image requires this job to pass.

Local verification on 2026-10-04 (amd64 cloud agent, host-network workaround
because nested-docker bridge had no outbound HTTPS):

- Unit tests: **27 passed**
- Image size: **1.47 GiB** (1,539,801,676 bytes), Python 3.14.2 / Node v24.12.0
- MariaDB **11.8.9**

GitHub Actions image smoke on `241c9fb` (**passed**):

- Fresh provisioning: **328s**
- Repeat `devctl sync`: **0s**
- `devctl doctor` → Environment healthy
- HTTP, Socket.IO, restart persistence, and 9 in-container smoke tests passed
- MariaDB **11.8.9**
- Sites `cohenix.localhost` and `second.localhost` with frappe + erpnext + hrms
- `assets.json` present
- HTTP `frappe.ping` → `pong` on both Host headers
- Socket.IO on 9000, Redis on 11000/13000, workers and scheduler running
- `devctl doctor` → Environment healthy
- Container restart: site files and MariaDB databases survived; `devctl start`
  restored HTTP pong
- Repeat `devctl sync --extra-sites second.localhost` with no config changes:
  **0 seconds** (`nothing to do`)
- Fresh path: Pilot install + bench init **56s**; Frappe site create then
  ERPNext/HRMS install on two sites completed on the recovery run (interrupted
  once by the packaging/symlink bug, then resumed without rebuilding the bench)
- `pilot frappe execute frappe.ping` → `pong`
- `run-tests` is enabled (`allow_tests=1`) and Frappe test extras (hypothesis,
  responses, freezegun, Faker) are installed into the bench env. A full
  `run-tests` on the default HR site currently fails while generating records
  for ERPNext's `Payment Gateway` DocType (the `payments` app is not in the
  `hr` profile). Use `devctl profile use frappe` for framework-only tests, or
  add `payments` via the integrations profile.

Nested Docker in this VM cannot reach GitHub/PyPI on the default bridge
(`iptables=false` + vfs). GitHub Actions remains the official networked smoke
path. Compose itself is unchanged (services share a user-defined network).

### Image size and provisioning times

Local amd64 image build (`cohenix-frappe-dev:v16-test`, vfs storage):

- Image size: **1.47 GiB** (1,539,801,676 bytes)
- Python: 3.14.2 (prebuilt CPython via uv, ~1s install, no pyenv compile)
- Node: v24.12.0
- Yarn: 1.22.22
- uv: 0.11.33

Measured GitHub Actions image smoke on `241c9fb`:

| Metric | Value |
|---|---|
| Fresh `devctl sync` (hr, two sites, ERPNext + HRMS) | **328s** |
| Repeat `devctl sync` (fingerprint match) | **0s** |
| Pilot install + bench init (local recovery run) | **56s** |

CI records `FRESH_SECONDS` / `REPEAT_SECONDS` into
`docs/last-smoke-metrics.txt` when `.github/workflows/image.yml` runs.

The daily-loop improvement versus the previous `resources/Dockerfile`
bootstrap is **image pull instead of compile**. The old image built Python
3.10 and 3.14 with pyenv and Node 16 and 24 with nvm on every rebuild.
Those compiles were not re-measured here; they are the cost the v16 image
removes. After the image exists, provisioning time is Frappe/ERPNext work
(clone, wheel install, `new-site`, `install-app`), which is unchanged in
kind and now skippable on repeat via fingerprints.

The design target is:

- image pull, not Python compile, on a normal Dev Container rebuild
- repeat `devctl sync` with no config changes returns immediately after
  fingerprint comparison
- MariaDB data, Pilot benches, and package caches survive container recreate

### Progress UX

`devctl sync` and `devctl start` print a non-interactive stage reporter
(`cohenix_dev/progress.py`):

- header: profile, Python, Node, Pilot, bench, sites, apps
- numbered `>>> [n/N]` / `<<< [n/N] done (time)` banners
- 15s heartbeat while a stage is still running
- skipped stages when the fingerprint plan has nothing to do
- end-of-run timing table
- GitHub Actions `::group::` sections when `GITHUB_ACTIONS=true`

No prompts. Pilot's own `[1/12]` init output is left intact and nested
under the Cohenix stage. Compose forwards `GITHUB_ACTIONS` and `CI` into
the Frappe service so CI logs group the same way.

## Recommended next steps

1. Run the image workflow on `version-16_cohenix` so GHCR receives the first
   multi-arch `v16` tag.
2. Promote Pilot only after a green canary report for v0.0.55-pre-alpha (or
   newer) and a human review of `config/pilot-compat.toml`.
3. Add Codespaces machine prebuilds once the published image exists.
4. If Cohenix private app URLs should replace public Frappe remotes in a
   profile, put them in `config/profiles.toml` — do not invent names.
5. Consider pinning MariaDB by digest after the first production week of 11.8.9.
