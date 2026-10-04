"""MariaDB helpers for Compose-backed Pilot benches."""

from __future__ import annotations

import json
import os

from cohenix_dev.config import SAFE_SQL_IDENTIFIER, Settings
from cohenix_dev.errors import CohenixError
from cohenix_dev.output import cprint
from cohenix_dev.runtime.pilot import bench_root
from cohenix_dev.util import run_command


def repair_db_login_scope(settings: Settings, site_name: str) -> None:
    """Grant the site's DB user access from any host.

    frappe's new-site scopes the user to the host the root connection came from
    (SELECT USER()), which in compose is the frappe container's IP and changes
    when containers are recreated. Pilot builds the new-site command itself and
    does not pass --mariadb-user-host-login-scope.
    """
    if not settings.db_login_scope or settings.db_type != "mariadb":
        return

    site_config_path = bench_root(settings) / "sites" / site_name / "site_config.json"
    site_config = json.loads(site_config_path.read_text(encoding="utf-8"))
    db_name = site_config["db_name"]
    db_user = site_config.get("db_user") or db_name
    db_password = site_config["db_password"]

    for value in (db_name, db_user):
        if not SAFE_SQL_IDENTIFIER.match(value):
            raise CohenixError(f"Refusing to build SQL for unexpected identifier: {value!r}")

    scope = settings.db_login_scope.replace("'", "''")
    password = db_password.replace("'", "''")
    statements = (
        f"CREATE USER IF NOT EXISTS '{db_user}'@'{scope}' IDENTIFIED BY '{password}';"
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'{scope}';"
        "FLUSH PRIVILEGES;"
    )
    cprint(f"Granting {db_user}@{settings.db_login_scope} on {db_name} ...", level=3)
    run_command(
        [
            "mariadb",
            "-h",
            settings.db_host or "mariadb",
            "-P",
            str(settings.db_port or 3306),
            "-u",
            settings.db_root_username,
            "-e",
            statements,
        ],
        env={**os.environ, "MYSQL_PWD": settings.db_root_password},
    )


def _mariadb_args(settings: Settings) -> list[str]:
    return [
        "mariadb",
        "-h",
        settings.db_host or "mariadb",
        "-P",
        str(settings.db_port or 3306),
        "-u",
        settings.db_root_username,
    ]


def mariadb_version(settings: Settings) -> str:
    env = {**os.environ, "MYSQL_PWD": settings.db_root_password}
    import subprocess

    result = subprocess.run(
        [*_mariadb_args(settings), "-N", "-e", "SELECT VERSION();"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def mariadb_can_connect(settings: Settings) -> bool:
    env = {**os.environ, "MYSQL_PWD": settings.db_root_password}
    import subprocess

    result = subprocess.run(
        [*_mariadb_args(settings), "-e", "SELECT 1;"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result.returncode == 0
