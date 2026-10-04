"""Safe reset commands with explicit scopes."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from cohenix_dev.config import Settings
from cohenix_dev.errors import DestructiveResetAborted
from cohenix_dev.output import cprint, plain
from cohenix_dev.runtime.pilot import bench_root, benches_dir, run_pilot
from cohenix_dev.runtime.processes import stop_bench


def confirm_or_abort(settings: Settings, plan: list[str]) -> None:
    plain("This will delete:")
    for line in plan:
        plain(f"  - {line}")
    plain("Developer source in this repository is not deleted.")
    if settings.yes:
        return
    if not sys.stdin.isatty():
        raise DestructiveResetAborted("Refusing destructive reset without --yes in a non-interactive session.")
    answer = input("Type 'reset' to continue: ").strip()
    if answer != "reset":
        raise DestructiveResetAborted("Reset cancelled.")


def reset_site(settings: Settings, site: str) -> None:
    root = bench_root(settings)
    site_dir = root / "sites" / site
    plan = [f"Site directory {site_dir}", f"MariaDB database for {site}"]
    confirm_or_abort(settings, plan)
    stop_bench(settings)
    if site_dir.exists():
        run_pilot(settings, "--bench", settings.bench_name, "drop-site", site, "--force")
        if site_dir.exists():
            shutil.rmtree(site_dir)
    cprint(f"Site {site} removed. Run `devctl site create {site}` or `devctl sync` to recreate it.", level=2)


def reset_caches(settings: Settings) -> None:
    targets = [
        Path.home() / ".cache" / "uv",
        Path.home() / ".cache" / "yarn",
        Path.home() / ".npm",
        bench_root(settings) / "sites" / "assets",
    ]
    plan = [str(path) for path in targets if path.exists()]
    confirm_or_abort(settings, plan or ["(nothing cached)"])
    for path in targets:
        if path.is_dir():
            shutil.rmtree(path)
            path.mkdir(parents=True, exist_ok=True)
    cprint("Caches cleared.", level=2)


def reset_bench(settings: Settings) -> None:
    root = bench_root(settings)
    plan = [
        f"{root}/env (Python environment)",
        f"{root}/sites (sites, assets, database bindings)",
        f"{root}/config, logs, pids, node_modules",
        "App checkouts under apps/ are kept",
    ]
    confirm_or_abort(settings, plan)
    stop_bench(settings)
    for name in ("env", "sites", "config", "logs", "pids", "node_modules"):
        path = root / name
        if path.exists():
            shutil.rmtree(path)
    fingerprint = root / ".cohenix"
    if fingerprint.exists():
        shutil.rmtree(fingerprint)
    provenance = root / ".provisioning.json"
    if provenance.exists():
        provenance.unlink()
    cprint("Bench runtime reset. App repositories were kept. Run `devctl sync`.", level=2)


def reset_all(settings: Settings) -> None:
    root = benches_dir(settings)
    plan = [
        f"All benches under {root}",
        "Pilot admin virtualenv",
        "Workspace symlink to the bench",
        "Not deleted: this git repository, SSH keys, or files outside PILOT_DIR",
    ]
    confirm_or_abort(settings, plan)
    stop_bench(settings)
    if root.exists():
        shutil.rmtree(root)
    admin = Path(settings.pilot_dir) / ".admin-venv"
    if admin.exists():
        shutil.rmtree(admin)
    link = Path(settings.workspace) / settings.bench_name
    if link.is_symlink():
        link.unlink()
    cprint("Environment reset. Run `devctl sync` to provision again.", level=2)
