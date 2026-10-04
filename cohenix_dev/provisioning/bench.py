"""Pilot bench creation, configuration, and workspace symlink."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from cohenix_dev.config import DEFAULT_ADMIN_PORT, DEFAULT_HTTP_PORT, DEFAULT_SOCKETIO_PORT, Settings
from cohenix_dev.errors import CohenixError
from cohenix_dev.output import cprint
from cohenix_dev.provisioning.apps import apps_for_bench
from cohenix_dev.runtime.pilot import bench_root, benches_dir, import_pilot_config, run_pilot


def clear_incomplete_venv(venv: Path) -> None:
    """Drop a venv directory that exists but has no interpreter in it."""
    if not venv.is_dir() or (venv / "bin" / "python").exists():
        return
    cprint(f"Removing incomplete virtualenv {venv} ...", level=3)
    shutil.rmtree(venv)


def bench_is_initialised(settings: Settings) -> bool:
    root = bench_root(settings)
    return (root / "bench.toml").exists() and (root / "apps" / "frappe").is_dir()


def sibling_bench_ports(settings: Settings) -> dict[int, str]:
    _, bench_config = import_pilot_config(settings)
    claimed: dict[int, str] = {}
    for toml_path in sorted(benches_dir(settings).glob("*/bench.toml")):
        name = toml_path.parent.name
        if name == settings.bench_name:
            continue
        try:
            config = bench_config.read(toml_path.parent)
        except Exception:  # noqa: BLE001
            continue
        for port in (config.http_port, config.socketio_port, config.admin.port):
            claimed[port] = name
    return claimed


def bench_ports(settings: Settings) -> dict[str, int]:
    _, bench_config = import_pilot_config(settings)
    offset = bench_config.current_port_offset(bench_root(settings) / "bench.toml")
    defaults = {"http": DEFAULT_HTTP_PORT, "socketio": DEFAULT_SOCKETIO_PORT, "admin": DEFAULT_ADMIN_PORT}
    chosen = {"http": settings.http_port, "socketio": settings.socketio_port, "admin": settings.admin_port}
    ports = {role: value if value != defaults[role] else value + offset for role, value in chosen.items()}
    if offset:
        cprint(f"Pilot picked port offset {offset} for this bench", level=3)
    claimed = sibling_bench_ports(settings)
    problems: list[str] = []
    for role, port in sorted(ports.items(), key=lambda item: item[1]):
        if port in claimed:
            problems.append(f"  {role} port {port} is already used by bench '{claimed[port]}'")
    if len(set(ports.values())) != len(ports):
        problems.append(f"  two roles were given the same port: {ports}")
    if problems:
        raise CohenixError(
            "Cannot allocate ports for this bench:\n"
            + "\n".join(problems)
            + "\nPass --http-port/--socketio-port/--admin-port explicitly."
        )
    return ports


def configure_bench(settings: Settings) -> None:
    app_config, bench_config = import_pilot_config(settings)
    root = bench_root(settings)
    ports = bench_ports(settings)
    db_host = settings.db_host or ("mariadb" if settings.db_type == "mariadb" else "postgresql")
    cprint("Writing bench.toml ...", level=2)
    with bench_config.open(root, mode="rw") as config:
        config.python_version = settings.py_version
        config.apps = [
            app_config(name=spec.name, repo=spec.repo, branch=spec.branch) for spec in apps_for_bench(settings)
        ]
        config.http_port = ports["http"]
        config.socketio_port = ports["socketio"]
        config.admin.port = ports["admin"]
        config.admin.password = settings.admin_ui_password or settings.admin_password
        config.allow_developer_mode = True
        if settings.db_type == "postgres":
            config.postgres.existing = True
            config.postgres.host = db_host
            config.postgres.port = settings.db_port or 5432
            config.postgres.admin_user = settings.db_root_username
            config.postgres.root_password = settings.db_root_password
        else:
            config.mariadb.existing = True
            config.mariadb.host = db_host
            config.mariadb.port = settings.db_port or 3306
            config.mariadb.admin_user = settings.db_root_username
            config.mariadb.root_password = settings.db_root_password
            config.mariadb.socket_path = ""
    for spec in apps_for_bench(settings):
        cprint(f"  app {spec.name} <- {spec.repo} @ {spec.branch}", level=3)


def set_common_site_config(settings: Settings, values: dict) -> None:
    path = bench_root(settings) / "sites" / "common_site_config.json"
    config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    config.update(values)
    path.write_text(json.dumps(config, indent=1) + "\n", encoding="utf-8")
    for key, value in values.items():
        cprint(f"Set common site config {key}={value}", level=3)


def link_bench_into_workspace(settings: Settings) -> None:
    link = Path(settings.workspace) / settings.bench_name
    if not Path(settings.workspace).exists():
        link = Path(os.getcwd()) / settings.bench_name
    if link.exists() and not link.is_symlink():
        cprint(f"{link} already exists and is not a symlink, leaving it alone", level=3)
        return
    if link.is_symlink():
        link.unlink()
    link.symlink_to(bench_root(settings))
    cprint(f"Linked {link} -> {bench_root(settings)}", level=3)


def init_bench_if_not_exist(settings: Settings) -> bool:
    """Create or resume the bench. Returns True if init ran."""
    from cohenix_dev.runtime.processes import ensure_bench_config_files

    clear_incomplete_venv(bench_root(settings) / "env")
    if bench_is_initialised(settings):
        cprint("Bench already exists. Only site will be created", level=3)
        ensure_bench_config_files(settings)
        link_bench_into_workspace(settings)
        return False
    if (bench_root(settings) / "bench.toml").exists():
        cprint(f"Bench {settings.bench_name} is half-built, resuming ...", level=3)
    else:
        cprint(f"Creating bench {settings.bench_name} ...", level=2)
        run_pilot(settings, "new", settings.bench_name, "--database", settings.db_type)
    configure_bench(settings)
    cprint("Initialising bench (clone + install apps, this takes a while) ...", level=2)
    run_pilot(settings, "--bench", settings.bench_name, "init")
    set_common_site_config(settings, {"developer_mode": 1})
    link_bench_into_workspace(settings)
    return True
