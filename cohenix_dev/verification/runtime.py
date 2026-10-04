"""Static verification of the provisioned development environment."""

from __future__ import annotations

import sys

from cohenix_dev.config import Settings
from cohenix_dev.errors import VerifyError
from cohenix_dev.output import cprint
from cohenix_dev.provisioning.apps import apps_for_bench
from cohenix_dev.provisioning.sites import site_installed_apps
from cohenix_dev.runtime.pilot import bench_root, installed_pilot_version, pilot_bin
from cohenix_dev.util import which


def collect_verify_errors(settings: Settings) -> list[str]:
    errors: list[str] = []
    for command in ("git", "mariadb", "node", "redis-server", "uv", "yarn"):
        if which(command) is None:
            errors.append(f"required command is missing: {command}")

    expected_python = settings.py_version
    actual_python = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if actual_python != expected_python and not actual_python.startswith(f"{expected_python}."):
        errors.append(f"Python {expected_python} requested, but installer runs on {actual_python}")

    installed = installed_pilot_version(settings)
    if not pilot_bin(settings).is_file():
        errors.append(f"Pilot executable is missing: {pilot_bin(settings)}")
    if settings.pilot_version != "latest" and installed != settings.pilot_version:
        errors.append(f"Pilot {settings.pilot_version} requested, but {installed} is installed")

    root = bench_root(settings)
    if not (root / "bench.toml").is_file():
        errors.append(f"bench manifest is missing: {root / 'bench.toml'}")
    if not (root / "apps" / "frappe").is_dir():
        errors.append("Frappe app checkout is missing")
    if not (root / "sites" / "assets" / "assets.json").is_file():
        errors.append("built asset manifest is missing")

    expected_apps = [spec.name for spec in apps_for_bench(settings)]
    for name in expected_apps:
        if not (root / "apps" / name).is_dir():
            errors.append(f"app checkout is missing: {name}")
    for site_name in settings.site_names():
        site_config = root / "sites" / site_name / "site_config.json"
        if not site_config.is_file():
            errors.append(f"site is missing: {site_name}")
            continue
        installed_apps = site_installed_apps(settings, site_name)
        missing_apps = [name for name in expected_apps if name not in installed_apps]
        if missing_apps:
            errors.append(f"site {site_name} is missing apps: {', '.join(missing_apps)}")
    return errors


def verify_installation(settings: Settings) -> None:
    errors = collect_verify_errors(settings)
    if errors:
        cprint("Development environment verification failed:", level=1)
        for error in errors:
            cprint(f"  - {error}", level=1)
        raise VerifyError("Development environment verification failed")
    installed = installed_pilot_version(settings)
    actual_python = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    expected_apps = [spec.name for spec in apps_for_bench(settings)]
    cprint(
        f"Verified Pilot {installed}, Python {actual_python}, "
        f"{len(expected_apps)} apps and {len(settings.site_names())} site(s).",
        level=2,
    )
