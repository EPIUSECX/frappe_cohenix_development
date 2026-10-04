"""devctl command-line interface. No command requires interactive input in CI."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from cohenix_dev import __version__
from cohenix_dev.config import Settings, list_profile_names, settings_from_env, write_local_profile
from cohenix_dev.errors import CohenixError
from cohenix_dev.output import cprint, plain


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--bench-name", default=None)
    parser.add_argument("--site-name", default=None)
    parser.add_argument("--pilot-dir", default=None)
    parser.add_argument("--pilot-version", default=None)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Confirm destructive actions without a prompt")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devctl",
        description="Cohenix Frappe v16 development environment CLI.",
    )
    parser.add_argument("--version", action="version", version=f"devctl {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="Provision or update the environment")
    _add_common(sync)
    sync.add_argument("--apps-json", default=None)
    sync.add_argument("--extra-sites", nargs="*", default=None)
    sync.add_argument("--admin-password", default=None)
    sync.add_argument("--db-type", default=None)
    sync.add_argument("--db-root-password", default=None)
    sync.add_argument("--no-verify", action="store_true")

    doctor = sub.add_parser("doctor", help="Diagnose the environment")
    _add_common(doctor)

    verify = sub.add_parser("verify", help="Verify the provisioned bench without changing it")
    _add_common(verify)

    status = sub.add_parser("status", help="Short environment status")
    _add_common(status)

    start = sub.add_parser("start", help="Start Pilot processes")
    _add_common(start)
    stop = sub.add_parser("stop", help="Stop Pilot processes")
    _add_common(stop)
    restart = sub.add_parser("restart", help="Restart Pilot processes")
    _add_common(restart)

    site = sub.add_parser("site", help="Site operations")
    site_sub = site.add_subparsers(dest="site_command", required=True)
    site_create = site_sub.add_parser("create", help="Create a site")
    _add_common(site_create)
    site_create.add_argument("name")
    site_create.add_argument("--admin-password", default=None)
    site_reset = site_sub.add_parser("reset", help="Drop and remove a site")
    _add_common(site_reset)
    site_reset.add_argument("name")

    app = sub.add_parser("app", help="Application operations")
    app_sub = app.add_subparsers(dest="app_command", required=True)
    app_add = app_sub.add_parser("add", help="Add an app repository")
    _add_common(app_add)
    app_add.add_argument("repository")
    app_add.add_argument("--branch", default=None)
    app_add.add_argument("--name", default=None)
    app_remove = app_sub.add_parser("remove", help="Remove an app from the overlay")
    _add_common(app_remove)
    app_remove.add_argument("app")

    profile = sub.add_parser("profile", help="Application profile operations")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    profile_use = profile_sub.add_parser("use", help="Select a profile for later syncs")
    _add_common(profile_use)
    profile_use.add_argument("name")
    profile_list = profile_sub.add_parser("list", help="List available profiles")
    _add_common(profile_list)

    reset = sub.add_parser("reset", help="Destructive reset (requires --yes in CI)")
    _add_common(reset)
    reset.add_argument("--site", metavar="NAME", default=None, help="Reset one site")
    reset.add_argument("--caches", action="store_true")
    reset.add_argument("--bench", action="store_true")
    reset.add_argument("--all", action="store_true", dest="reset_all")
    return parser


def settings_from_args(args: argparse.Namespace) -> Settings:
    extra_sites = getattr(args, "extra_sites", None)
    overrides = {
        "bench_name": getattr(args, "bench_name", None),
        "site_name": getattr(args, "site_name", None),
        "pilot_dir": getattr(args, "pilot_dir", None),
        "pilot_version": getattr(args, "pilot_version", None),
        "profile": getattr(args, "profile", None),
        "verbose": bool(getattr(args, "verbose", False)),
        "yes": bool(getattr(args, "yes", False)),
        "apps_json": getattr(args, "apps_json", None),
        "admin_password": getattr(args, "admin_password", None),
        "db_type": getattr(args, "db_type", None),
        "db_root_password": getattr(args, "db_root_password", None),
    }
    settings = settings_from_env(overrides)
    if extra_sites:
        settings.extra_sites = list(extra_sites)
    return settings


def dispatch(args: argparse.Namespace) -> int:
    command = args.command
    if command == "profile" and args.profile_command == "list":
        for name in list_profile_names():
            plain(name)
        return 0

    settings = settings_from_args(args)

    if command == "sync":
        from cohenix_dev.provisioning.sync import sync_environment

        sync_environment(settings, verify=not args.no_verify)
        return 0
    if command == "doctor":
        from cohenix_dev.doctor import render_doctor, run_checks

        return render_doctor(settings, run_checks(settings))
    if command == "verify":
        from cohenix_dev.verification.runtime import verify_installation

        verify_installation(settings)
        return 0
    if command == "status":
        from cohenix_dev.doctor import render_doctor, run_checks

        return render_doctor(settings, run_checks(settings))
    if command == "start":
        from cohenix_dev.runtime.processes import start_bench

        start_bench(settings)
        return 0
    if command == "stop":
        from cohenix_dev.runtime.processes import stop_bench

        stop_bench(settings)
        return 0
    if command == "restart":
        from cohenix_dev.runtime.processes import restart_bench

        restart_bench(settings)
        return 0
    if command == "site":
        return _site(settings, args)
    if command == "app":
        return _app(settings, args)
    if command == "profile":
        return _profile(settings, args)
    if command == "reset":
        return _reset(settings, args)
    raise CohenixError(f"Unknown command {command}")


def _site(settings: Settings, args: argparse.Namespace) -> int:
    if args.site_command == "create":
        from cohenix_dev.provisioning.apps import apps_for_bench
        from cohenix_dev.provisioning.sites import provision_site
        from cohenix_dev.runtime.processes import redis_running

        settings.extra_sites = [name for name in settings.extra_sites + [args.name] if name != settings.site_name]
        if args.name != settings.site_name:
            # Keep default site, add this one.
            pass
        app_names = [spec.name for spec in apps_for_bench(settings)]
        with redis_running(settings):
            provision_site(settings, args.name, app_names)
        return 0
    if args.site_command == "reset":
        from cohenix_dev.reset import reset_site

        reset_site(settings, args.name)
        return 0
    raise CohenixError(f"Unknown site command {args.site_command}")


def _app(settings: Settings, args: argparse.Namespace) -> int:
    if args.app_command == "add":
        from cohenix_dev.provisioning.apps import add_overlay_app

        spec = add_overlay_app(settings, args.repository, branch=args.branch, name=args.name)
        cprint(f"Added {spec.name}. Run `devctl sync` to install it on sites.", level=2)
        return 0
    if args.app_command == "remove":
        from cohenix_dev.provisioning.apps import remove_overlay_app

        remove_overlay_app(settings, args.app)
        cprint(f"Removed {args.app} from the overlay.", level=2)
        return 0
    raise CohenixError(f"Unknown app command {args.app_command}")


def _profile(settings: Settings, args: argparse.Namespace) -> int:
    if args.profile_command == "use":
        path = write_local_profile(settings.workspace_path, args.name)
        cprint(f"Profile {args.name} selected ({path}). Run `devctl sync` to apply it.", level=2)
        return 0
    raise CohenixError(f"Unknown profile command {args.profile_command}")


def _reset(settings: Settings, args: argparse.Namespace) -> int:
    from cohenix_dev.reset import reset_all, reset_bench, reset_caches, reset_site

    if args.site:
        reset_site(settings, args.site)
        return 0
    if args.caches:
        reset_caches(settings)
        return 0
    if args.bench:
        reset_bench(settings)
        return 0
    if args.reset_all:
        reset_all(settings)
        return 0
    raise CohenixError("Specify --site NAME, --caches, --bench, or --all")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return dispatch(args)
    except CohenixError as exc:
        cprint(str(exc), level=1)
        return exc.exit_code
