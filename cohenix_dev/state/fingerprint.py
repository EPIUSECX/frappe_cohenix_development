"""Environment fingerprint: requested config vs what is already provisioned."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from cohenix_dev.config import PROVISIONER_SCHEMA, Settings, image_ref, load_toolchain
from cohenix_dev.provisioning.apps import app_commit, apps_for_bench
from cohenix_dev.runtime.pilot import bench_root, installed_pilot_version
from cohenix_dev.util import command_output, write_text

FINGERPRINT_NAME = Path(".cohenix") / "fingerprint.json"


@dataclass
class AppFingerprint:
    name: str
    repo: str
    branch: str
    resolved_commit: str = "unknown"


@dataclass
class Fingerprint:
    schema_version: int
    profile: str
    image: str
    architecture: str
    python: str
    node: str
    uv: str
    pilot: str
    mariadb_image: str
    database_version: str
    frappe_branch: str
    apps: list[AppFingerprint] = field(default_factory=list)
    sites: list[str] = field(default_factory=list)
    bench_name: str = "development-bench"

    def requested_key(self) -> dict[str, Any]:
        """Fields that mean 'the operator asked for this'. Commits are observations."""
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "image": self.image,
            "python": _major_minor(self.python),
            "node": _major_minor(self.node),
            "pilot": self.pilot,
            "mariadb_image": self.mariadb_image,
            "frappe_branch": self.frappe_branch,
            "apps": [(app.name, app.repo, app.branch) for app in self.apps],
            "sites": list(self.sites),
            "bench_name": self.bench_name,
        }

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["apps"] = [asdict(app) for app in self.apps]
        return data


def _major_minor(version: str) -> str:
    parts = version.lstrip("v").split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else version


def fingerprint_path(settings: Settings) -> Path:
    return bench_root(settings) / FINGERPRINT_NAME


def load_fingerprint(settings: Settings) -> Fingerprint | None:
    path = fingerprint_path(settings)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    apps = [AppFingerprint(**app) for app in data.get("apps") or []]
    data["apps"] = apps
    known = {k: data[k] for k in Fingerprint.__dataclass_fields__ if k in data}
    return Fingerprint(**known)


def save_fingerprint(settings: Settings, fingerprint: Fingerprint) -> Path:
    path = fingerprint_path(settings)
    write_text(path, json.dumps(fingerprint.as_dict(), indent=2, sort_keys=True) + "\n")
    return path


def desired_fingerprint(settings: Settings, *, database_version: str = "unknown") -> Fingerprint:
    toolchain = load_toolchain()
    python = command_output("python3", "--version").replace("Python ", "") or settings.py_version
    node = command_output("node", "--version")
    uv = command_output("uv", "--version")
    apps = [
        AppFingerprint(
            name=spec.name,
            repo=spec.repo,
            branch=spec.branch,
            resolved_commit=app_commit(bench_root(settings) / "apps" / spec.name),
        )
        for spec in apps_for_bench(settings)
    ]
    return Fingerprint(
        schema_version=PROVISIONER_SCHEMA,
        profile=settings.profile,
        image=os.environ.get("COHENIX_IMAGE_REF") or image_ref(toolchain),
        architecture=platform.machine(),
        python=python,
        node=node,
        uv=uv,
        pilot=settings.pilot_version,
        mariadb_image=str(toolchain["database"]["mariadb_image"]),
        database_version=database_version,
        frappe_branch=settings.frappe_branch,
        apps=apps,
        sites=settings.site_names(),
        bench_name=settings.bench_name,
    )


@dataclass
class SyncPlan:
    initialize_bench: bool = False
    create_sites: list[str] = field(default_factory=list)
    install_apps: dict[str, list[str]] = field(default_factory=dict)
    migrate_sites: list[str] = field(default_factory=list)
    rebuild_assets: bool = False
    deepen_history: bool = False
    repair: list[str] = field(default_factory=list)
    skip_reason: str | None = None

    def is_noop(self) -> bool:
        return self.skip_reason is not None

    def describe(self) -> list[str]:
        if self.skip_reason:
            return [self.skip_reason]
        lines: list[str] = []
        if self.initialize_bench:
            lines.append("Initialize the Pilot bench and install apps")
        for site in self.create_sites:
            lines.append(f"Create site {site}")
        for site, apps in self.install_apps.items():
            lines.append(f"Install {', '.join(apps)} on {site}")
        for site in self.migrate_sites:
            lines.append(f"Run migrations on {site}")
        if self.rebuild_assets:
            lines.append("Build missing asset manifests")
        if self.deepen_history:
            lines.append("Deepen shallow app clones")
        lines.extend(self.repair)
        return lines or ["No changes"]


def plan_sync(settings: Settings, current: Fingerprint | None, desired: Fingerprint) -> SyncPlan:
    from cohenix_dev.provisioning.bench import bench_is_initialised
    from cohenix_dev.provisioning.sites import site_installed_apps
    from cohenix_dev.runtime.pilot import bench_root as root_of

    plan = SyncPlan()
    root = root_of(settings)
    if not bench_is_initialised(settings):
        plan.initialize_bench = True
        plan.create_sites = list(settings.site_names())
        plan.rebuild_assets = True
        plan.deepen_history = True
        plan.repair.append("Recover incomplete Python environments if present")
        return plan

    if current and current.requested_key() == desired.requested_key():
        missing_manifest = not (root / "sites" / "assets" / "assets.json").is_file()
        incomplete_env = (root / "env").is_dir() and not (root / "env" / "bin" / "python").exists()
        missing_redis = not (root / "config" / "redis_cache.conf").exists()
        if not missing_manifest and not incomplete_env and not missing_redis:
            plan.skip_reason = "Requested configuration matches the provisioned environment"
            return plan
        if missing_manifest:
            plan.rebuild_assets = True
            plan.repair.append("Restore missing assets.json")
        if incomplete_env:
            plan.repair.append("Remove incomplete Python environment")
        if missing_redis:
            plan.repair.append("Regenerate Redis configuration")
        return plan

    existing_sites = {
        path.name for path in (root / "sites").iterdir() if path.is_dir() and (path / "site_config.json").exists()
    }
    for site in settings.site_names():
        if site not in existing_sites:
            plan.create_sites.append(site)
        else:
            installed = site_installed_apps(settings, site)
            missing = [app.name for app in desired.apps if app.name not in installed]
            if missing:
                plan.install_apps[site] = missing
                plan.migrate_sites.append(site)
    current_apps = {app.name: (app.repo, app.branch) for app in (current.apps if current else [])}
    desired_apps = {app.name: (app.repo, app.branch) for app in desired.apps}
    changed = [name for name, spec in desired_apps.items() if current_apps.get(name) != spec]
    if changed and not plan.migrate_sites:
        plan.migrate_sites = list(settings.site_names())
    if not (root / "sites" / "assets" / "assets.json").is_file():
        plan.rebuild_assets = True
    plan.deepen_history = True
    return plan
