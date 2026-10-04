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
| CLI undeclared `packaging` dependency | Fixed in 0.0.55 via `pilot._vendor.packaging`; pip fallback kept for the pin |
| CLI undeclared `pymysql` | Still required on pin and canary |
| No external Redis | Still required; image includes redis-server |
| `new-site` omits `--mariadb-user-host-login-scope` | Still repaired after create |
| `build_missing_assets` keys off symlink dirs, not `assets.json` | Still rebuilt by `devctl` |
| Release tarball clones apps `--depth 1` | Still deepened to 200 commits |
| `install.sh` wants host MariaDB/nginx/supervisor | Still avoided |
| `config/pids` missing for classic Bench | Still created |
| Admin UI default port 7000 | Still remapped to 8002 |
| Temporary Redis needed for `new-site` | Still started around site create |
| `VERSION=dev` would get full history; we will not lie about the version | Deepen workaround kept |

Do not set `PILOT_VERSION=latest` on the normal path.

## Test results

### Unit tests

Run with `python -m unittest discover -s tests -p 'test*.py' -v`.

Covered: Pilot release URLs and checksums, profiles, fingerprints, incomplete
venv recovery, CLI surface, toolchain agreement across Dockerfile/Compose/env,
SQL identifier guard, installer wrapper, Pilot workaround manifest.

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

### Image size and provisioning times

Local amd64 image build (`cohenix-frappe-dev:v16-test`, vfs storage):

- Image size: **1.47 GiB** (1,539,801,676 bytes)
- Python: 3.14.2 (prebuilt CPython via uv, ~1s install, no pyenv compile)
- Node: v24.12.0
- Yarn: 1.22.22
- uv: 0.11.33

Fresh and repeat provisioning times are recorded by CI into
`docs/last-smoke-metrics.txt` when `.github/workflows/image.yml` runs.
The design target is:

- image pull, not Python compile, on a normal Dev Container rebuild
- repeat `devctl sync` with no config changes returns immediately after
  fingerprint comparison
- MariaDB data, Pilot benches, and package caches survive container recreate

## Recommended next steps

1. Run the image workflow on `version-16_cohenix` so GHCR receives the first
   multi-arch `v16` tag.
2. Promote Pilot only after a green canary report for v0.0.55-pre-alpha (or
   newer) and a human review of `config/pilot-compat.toml`.
3. Add Codespaces machine prebuilds once the published image exists.
4. If Cohenix private app URLs should replace public Frappe remotes in a
   profile, put them in `config/profiles.toml` — do not invent names.
5. Consider pinning MariaDB by digest after the first production week of 11.8.9.
