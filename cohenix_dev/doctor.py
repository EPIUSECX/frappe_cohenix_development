"""devctl doctor: diagnose the complete environment with corrective guidance."""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass

from cohenix_dev.config import Settings, image_ref, load_toolchain
from cohenix_dev.output import cprint, plain
from cohenix_dev.runtime.database import mariadb_can_connect, mariadb_version
from cohenix_dev.runtime.pilot import bench_root, installed_pilot_version, pilot_bin
from cohenix_dev.util import command_output, which
from cohenix_dev.verification.bench import bench_layout_errors
from cohenix_dev.verification.health import inspect_processes
from cohenix_dev.verification.runtime import collect_verify_errors
from cohenix_dev.verification.sites import site_config_errors


@dataclass
class Check:
    group: str
    name: str
    ok: bool
    detail: str
    guidance: str = ""


def _ok(command: str) -> tuple[bool, str]:
    path = which(command)
    if not path:
        return False, "not on PATH"
    if command in {"python3", "node", "yarn", "uv", "mariadb", "redis-server"}:
        version = command_output(command, "--version")
        return True, version or path
    return True, path


def run_checks(settings: Settings) -> list[Check]:
    checks: list[Check] = []
    toolchain = load_toolchain()
    arch = platform.machine()
    checks.append(Check("platform", "Architecture", True, arch))
    image = os.environ.get("COHENIX_IMAGE_REF") or image_ref(toolchain)
    checks.append(Check("platform", "Image", True, image))

    py_ok, py_detail = _ok("python3")
    expected_py = str(toolchain["python"]["version"])
    if py_ok and expected_py.split(".")[:2] != sys.version.split()[0].split(".")[:2]:
        py_ok = False
        py_detail = f"{sys.version.split()[0]} (expected {expected_py})"
    checks.append(
        Check(
            "runtime",
            "Python",
            py_ok,
            py_detail if py_ok else f"{py_detail}; expected {expected_py}",
            "Rebuild the Dev Container from the Cohenix v16 image. Do not compile Python on the host.",
        )
    )
    node_ok, node_detail = _ok("node")
    expected_node = str(toolchain["node"]["version"]).split(".")[0]
    if node_ok and not node_detail.lstrip("v").startswith(expected_node):
        node_ok = False
    checks.append(
        Check(
            "runtime",
            "Node",
            node_ok,
            node_detail,
            "The v16 image ships Node 24. Rebuild the container rather than installing nvm locally.",
        )
    )
    yarn_ok, yarn_detail = _ok("yarn")
    checks.append(Check("runtime", "Yarn", yarn_ok, yarn_detail, "npm install -g yarn@1.22.22 inside the image."))
    uv_ok, uv_detail = _ok("uv")
    checks.append(Check("runtime", "uv", uv_ok, uv_detail, "The image should already contain the pinned uv release."))

    db_ok = mariadb_can_connect(settings)
    db_detail = mariadb_version(settings) if db_ok else "cannot connect"
    checks.append(
        Check(
            "services",
            "MariaDB",
            db_ok,
            db_detail,
            "Wait for the mariadb service healthcheck, then confirm DB_ROOT_PASSWORD matches compose.",
        )
    )

    redis_ok = which("redis-server") is not None
    checks.append(
        Check(
            "services",
            "Redis binary",
            redis_ok,
            which("redis-server") or "missing",
            "The v16 image includes redis-server because Pilot cannot use the compose Redis services.",
        )
    )

    pilot_ok = pilot_bin(settings).is_file()
    installed = installed_pilot_version(settings) if pilot_ok else "missing"
    if pilot_ok and installed != settings.pilot_version and settings.pilot_version != "latest":
        pilot_ok = False
    checks.append(
        Check(
            "pilot",
            "Pilot",
            pilot_ok,
            installed,
            f"Run `devctl sync`. Pinned release is {settings.pilot_version}. Do not set PILOT_VERSION=latest.",
        )
    )

    frappe_ok = (bench_root(settings) / "apps" / "frappe").is_dir()
    checks.append(
        Check(
            "bench",
            "Frappe",
            frappe_ok,
            settings.frappe_branch if frappe_ok else "checkout missing",
            "Run `devctl sync`. If a previous sync was interrupted, sync will resume.",
        )
    )

    for error in bench_layout_errors(settings):
        checks.append(Check("bench", "Layout", False, error, "Run `devctl sync` to repair the bench layout."))
    for error in site_config_errors(settings):
        checks.append(Check("site", "Site config", False, error, "Run `devctl site create` or `devctl sync`."))
    for error in collect_verify_errors(settings):
        if "site is missing" in error or "missing apps" in error:
            checks.append(Check("apps", "Required apps", False, error, "Run `devctl sync` to finish site provisioning."))
        elif "asset manifest" in error:
            checks.append(
                Check(
                    "assets",
                    "Asset manifest",
                    False,
                    error,
                    "Run `devctl sync`. Pilot links public/ folders without writing assets.json.",
                )
            )

    if frappe_ok:
        health = inspect_processes(settings)
        checks.append(
            Check(
                "processes",
                "Web",
                health.web,
                health.http_detail or ("listening" if health.web else "not listening"),
                "Run `devctl start`. Check /tmp/pilot-*.log if it exits immediately.",
            )
        )
        checks.append(
            Check(
                "processes",
                "Socket.IO",
                health.socketio,
                health.realtime_detail or ("not listening" if not health.socketio else "ok"),
                "Realtime shares the bench process set. Restart with `devctl restart`.",
            )
        )
        checks.append(
            Check(
                "processes",
                "Workers",
                health.workers,
                "running" if health.workers else "not detected",
                "Workers start with `devctl start`. Confirm Redis is up first.",
            )
        )
        checks.append(
            Check(
                "processes",
                "Scheduler",
                health.scheduler,
                "running" if health.scheduler else "not detected",
                "Scheduler starts with `devctl start`. Pilot's Procfile omits it; Cohenix adds the process.",
            )
        )
        checks.append(
            Check(
                "processes",
                "Redis",
                health.redis,
                "cache and queue listening" if health.redis else "Pilot Redis is not listening",
                "Pilot starts Redis itself. If ports are taken, stop leftover redis-server processes.",
            )
        )
        if health.web:
            checks.append(
                Check(
                    "site",
                    settings.site_name,
                    health.http_ok,
                    health.http_detail,
                    "Use http://cohenix.localhost:<http_port>/app and confirm the Host header.",
                )
            )

    # Port conflicts on the default HTTP port.
    from cohenix_dev.util import port_is_live

    if port_is_live(settings.http_port) and not frappe_ok:
        checks.append(
            Check(
                "ports",
                f"HTTP {settings.http_port}",
                False,
                "port is already in use before the bench exists",
                "Another environment is bound to this port. Use Dev Container forwarding instead of host publish.",
            )
        )
    return checks


def render_doctor(settings: Settings, checks: list[Check]) -> int:
    toolchain = load_toolchain()
    plain("Cohenix Development Environment")
    arch = next((c.detail for c in checks if c.name == "Architecture"), platform.machine())
    image = next((c.detail for c in checks if c.name == "Image"), image_ref(toolchain))
    plain(f"Image       {image}")
    plain(f"Architecture {arch}")
    groups = [
        ("runtime", "Runtime"),
        ("services", "Services"),
        ("pilot", "Pilot"),
        ("bench", "Bench"),
        ("apps", "Apps"),
        ("assets", "Assets"),
        ("site", "Site"),
        ("processes", "Processes"),
        ("ports", "Ports"),
    ]
    by_group: dict[str, list[Check]] = {}
    for check in checks:
        by_group.setdefault(check.group, []).append(check)
    failed = 0
    for group, title in groups:
        items = by_group.get(group) or []
        if not items:
            continue
        if group in {"runtime", "site", "processes"}:
            plain(title)
        for check in items:
            status = "OK" if check.ok else "FAIL"
            if not check.ok:
                failed += 1
                cprint(f"{check.name:<12} {check.detail:<18} {status}", level=1)
                if check.guidance:
                    cprint(f"  → {check.guidance}", level=3)
            else:
                plain(f"{check.name:<12} {check.detail:<18} {status}")
    if failed:
        cprint(f"Environment unhealthy ({failed} check(s) failed).", level=1)
        return 1
    cprint("Environment healthy.", level=2)
    return 0
