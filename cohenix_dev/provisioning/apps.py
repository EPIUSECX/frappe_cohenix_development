"""App lists, shallow-clone recovery, and overlay edits."""

from __future__ import annotations

import subprocess
from pathlib import Path

from cohenix_dev.config import (
    APP_HISTORY_DEPTH,
    SHALLOW_CLONE_MAX_COMMITS,
    AppSpec,
    Settings,
    load_toml,
)
from cohenix_dev.output import cprint
from cohenix_dev.runtime.pilot import bench_root, run_pilot
from cohenix_dev.util import write_text


def apps_for_bench(settings: Settings) -> list[AppSpec]:
    return settings.apps()


def app_commit_count(path: Path) -> int:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-list", "--count", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return 0
    return int(result.stdout.strip() or 0)


def app_commit(path: Path) -> str:
    if not (path / ".git").exists():
        return "unknown"
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def ensure_app_history(settings: Settings) -> None:
    """Deepen the app clones Pilot made at --depth 1."""
    for spec in apps_for_bench(settings):
        path = bench_root(settings) / "apps" / spec.name
        if not (path / ".git").exists():
            continue
        if app_commit_count(path) >= SHALLOW_CLONE_MAX_COMMITS:
            continue
        cprint(f"Deepening {spec.name} history to ~{APP_HISTORY_DEPTH} commits ...", level=3)
        result = subprocess.run(
            ["git", "-C", str(path), "fetch", f"--depth={APP_HISTORY_DEPTH}", "origin", spec.branch],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            cprint(
                f"Could not deepen {spec.name} ({result.stderr.strip()}).\n"
                "  Pilot may offer a downgrade as an 'update' for this app -- check the "
                "version numbers before accepting one.",
                level=3,
            )


def incomplete_app_checkouts(settings: Settings) -> list[str]:
    missing: list[str] = []
    root = bench_root(settings)
    for spec in apps_for_bench(settings):
        path = root / "apps" / spec.name
        if not path.is_dir():
            missing.append(spec.name)
            continue
        has_project = (path / "pyproject.toml").exists() or (path / "setup.py").exists()
        if spec.name == "frappe" and not (path / "frappe").exists():
            missing.append(spec.name)
        elif not has_project:
            missing.append(spec.name)
    return missing


def add_overlay_app(settings: Settings, repo: str, branch: str | None = None, name: str | None = None) -> AppSpec:
    spec = AppSpec(
        name=name or repo.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git"),
        repo=repo,
        branch=branch or settings.frappe_branch,
    )
    path = settings.overlay_path
    data: dict = {"apps": []}
    if path.exists():
        data = load_toml(path)
        data.setdefault("apps", [])
    apps = [app for app in data.get("apps", []) if app.get("name") != spec.name]
    apps.append(spec.as_dict())
    data["apps"] = apps
    _write_overlay(path, data)
    if (bench_root(settings) / "bench.toml").exists():
        cprint(f"Fetching {spec.name} into the bench ...", level=2)
        run_pilot(settings, "--bench", settings.bench_name, "get-app", spec.repo, "--branch", spec.branch)
    return spec


def remove_overlay_app(settings: Settings, name: str, *, from_sites: bool = True) -> None:
    path = settings.overlay_path
    data: dict = {"apps": [], "remove": []}
    if path.exists():
        data = load_toml(path)
        data.setdefault("apps", [])
        data.setdefault("remove", [])
    data["apps"] = [app for app in data.get("apps", []) if app.get("name") != name]
    if name not in data["remove"]:
        data["remove"].append(name)
    _write_overlay(path, data)
    if from_sites and (bench_root(settings) / "bench.toml").exists():
        for site in settings.site_names():
            site_dir = bench_root(settings) / "sites" / site
            if site_dir.exists():
                cprint(f"Uninstalling {name} from {site} ...", level=3)
                try:
                    run_pilot(settings, "--bench", settings.bench_name, "uninstall-app", site, name)
                except Exception as exc:  # noqa: BLE001
                    cprint(f"Could not uninstall {name} from {site}: {exc}", level=3)


def _write_overlay(path: Path, data: dict) -> None:
    lines = ["# Local app overlay. Not committed.\n"]
    if data.get("apps"):
        lines.append("apps = [\n")
        for app in data["apps"]:
            lines.append(
                "  { "
                f'name = "{app["name"]}", repo = "{app["repo"]}", branch = "{app["branch"]}"'
                " },\n"
            )
        lines.append("]\n")
    if data.get("remove"):
        quoted = ", ".join(f'"{name}"' for name in data["remove"])
        lines.append(f"remove = [{quoted}]\n")
    write_text(path, "".join(lines))
