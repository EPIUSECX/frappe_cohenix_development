"""Compatibility wrapper for `python installer.py`."""

from __future__ import annotations

import argparse
import os
import sys

from cohenix_dev.config import DEFAULT_ADMIN_PORT, DEFAULT_HTTP_PORT, DEFAULT_SOCKETIO_PORT, Settings
from cohenix_dev.errors import CohenixError
from cohenix_dev.output import cprint
from cohenix_dev.provisioning.sync import sync_environment
from cohenix_dev.runtime.pilot import installed_pilot_version, pilot_release_asset
from cohenix_dev.verification.runtime import verify_installation

__all__ = ["installed_pilot_version", "main", "pilot_release_asset"]


def get_args_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compatibility wrapper. Prefer `devctl sync`.",
    )
    parser.add_argument("-j", "--apps-json", type=str, default=None)
    parser.add_argument("-b", "--bench-name", type=str, default="development-bench")
    parser.add_argument("-s", "--site-name", type=str, default="cohenix.localhost")
    parser.add_argument("--extra-sites", type=str, nargs="*", default=[], metavar="NAME")
    parser.add_argument("-r", "--frappe-repo", type=str, default="https://github.com/frappe/frappe")
    parser.add_argument("-t", "--frappe-branch", type=str, default=os.getenv("FRAPPE_BRANCH", "version-16"))
    parser.add_argument("-p", "--py-version", type=str, default=os.getenv("PYTHON_VERSION", "3.14"))
    parser.add_argument("-n", "--node-version", type=str, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-a", "--admin-password", type=str, default="admin")
    parser.add_argument("-d", "--db-type", type=str, default="mariadb")
    parser.add_argument("--db-root-username", type=str, default="root")
    parser.add_argument("--db-root-password", type=str, default=os.getenv("DB_ROOT_PASSWORD", "123"))
    parser.add_argument("--db-host", type=str, default=None)
    parser.add_argument("--db-port", type=int, default=None)
    parser.add_argument("--db-login-scope", type=str, default="%")
    parser.add_argument("--pilot-dir", type=str, default=os.getenv("PILOT_DIR", "/home/frappe/pilot"))
    parser.add_argument(
        "--pilot-version",
        type=str,
        default=os.getenv("PILOT_VERSION", "v0.0.23-pre-alpha"),
    )
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT)
    parser.add_argument("--socketio-port", type=int, default=DEFAULT_SOCKETIO_PORT)
    parser.add_argument("--admin-port", type=int, default=DEFAULT_ADMIN_PORT)
    parser.add_argument("--admin-ui-password", type=str, default=None)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--profile", type=str, default=None)
    return parser


def settings_from_installer_args(args: argparse.Namespace) -> Settings:
    from cohenix_dev.config import settings_from_env

    overrides = {
        "bench_name": args.bench_name,
        "site_name": args.site_name,
        "extra_sites": list(args.extra_sites or []),
        "frappe_repo": args.frappe_repo,
        "frappe_branch": args.frappe_branch,
        "py_version": args.py_version,
        "node_version": args.node_version,
        "verbose": args.verbose,
        "admin_password": args.admin_password,
        "db_type": args.db_type,
        "db_root_username": args.db_root_username,
        "db_root_password": args.db_root_password,
        "db_host": args.db_host,
        "db_port": args.db_port,
        "db_login_scope": args.db_login_scope,
        "pilot_dir": args.pilot_dir,
        "pilot_version": args.pilot_version,
        "http_port": args.http_port,
        "socketio_port": args.socketio_port,
        "admin_port": args.admin_port,
        "admin_ui_password": args.admin_ui_password,
        "apps_json": args.apps_json,
        "profile": args.profile,
    }
    settings = settings_from_env(overrides)
    settings.extra_sites = list(args.extra_sites or [])
    return settings


def main(argv: list[str] | None = None) -> int:
    parser = get_args_parser()
    args = parser.parse_args(argv)
    try:
        settings = settings_from_installer_args(args)
        if args.verify_only:
            verify_installation(settings)
            return 0
        sync_environment(settings)
        return 0
    except CohenixError as exc:
        cprint(str(exc), level=1)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
