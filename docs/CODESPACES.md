# GitHub Codespaces

This repository is Dev Container–first. Codespaces use the same
`.devcontainer/` stack. Prebuilds only pay off once the published image
`ghcr.io/epiusecx/cohenix-frappe-dev:v16` exists (the Development image
workflow publishes it from `version-16_cohenix`).

## What the prebuild bakes

GitHub Codespaces prebuilds run:

| Hook | Script | Purpose |
|---|---|---|
| `onCreateCommand` | `scripts/on-create.sh` | Volume ownership |
| `updateContentCommand` | `scripts/update-content.sh` | Editable `devctl` + optional pre-commit |

They **do not** run `postCreateCommand` / `postStartCommand`. Site provision
(`devctl sync`) and Pilot start still happen when a Codespace is created or
started, once MariaDB is healthy.

## Enable prebuilds (one-time, maintainers)

1. Confirm GHCR is ready: the **Codespaces prebuild gate** workflow must pass
   after a successful Development image publish, or run:

   ```bash
   docker pull ghcr.io/epiusecx/cohenix-frappe-dev:v16
   ```

2. Open **Settings → Codespaces → Set up prebuild**.
3. Branch: `version-16_cohenix`.
4. Configuration file: `.devcontainer/devcontainer.json`.
5. Trigger: **On configuration change** (saves Actions minutes) or a daily
   schedule. Avoid “Every push” until the image workflow is cheap.
6. Regions: only where the team works.
7. Template history: 2 is enough.

Machine size: the Dev Container declares `hostRequirements` of 4 CPUs / 8 GB /
32 GB. Prefer at least a 4-core Codespace.

## Developer path

1. Code → Codespaces → create on `version-16_cohenix` (prebuild badge when ready).
2. Wait for postStart (`devctl sync` / `start` / `doctor`).
3. Open http://cohenix.localhost:8000/app — Administrator / `admin`.

Optional:

```bash
devctl seed                 # demo company + sample employees
devctl debug enable        # attach debugpy on :5678 without stopping Pilot
```

## Troubleshooting

- Prebuild failed while GHCR was private: grant `read:packages` to the Codespaces
  environment or make the `v16` package visible to the org.
- First Codespace still slow: prebuild may be rebuilding; check Actions for
  `Codespaces Prebuilds`. Cold sync (~5 minutes for the `hr` profile) still
  runs once per volume.
- Nested Docker / custom runners are out of scope; use GitHub-hosted Codespaces.
