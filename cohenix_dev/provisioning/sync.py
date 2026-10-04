"""Idempotent environment sync."""

from __future__ import annotations

from cohenix_dev.config import Settings
from cohenix_dev.output import cprint
from cohenix_dev.provisioning.apps import ensure_app_history
from cohenix_dev.provisioning.assets import ensure_assets_built
from cohenix_dev.provisioning.bench import init_bench_if_not_exist
from cohenix_dev.provisioning.sites import create_sites, provision_site
from cohenix_dev.runtime.bench import ensure_classic_bench_compat
from cohenix_dev.runtime.pilot import ensure_pilot, ensure_redis_server
from cohenix_dev.runtime.processes import redis_running
from cohenix_dev.state.fingerprint import desired_fingerprint, load_fingerprint, plan_sync, save_fingerprint
from cohenix_dev.state.provenance import write_provisioning_record
from cohenix_dev.verification.runtime import verify_installation


def set_git_auto_setup_remote() -> None:
    from cohenix_dev.util import run_command

    try:
        run_command(["git", "config", "--global", "push.autoSetupRemote", "true"])
        cprint("Successfully set git global config auto setup remote", level=3)
    except Exception as exc:  # noqa: BLE001
        cprint(f"Failed to set git global config: {exc}", level=1)


def sync_environment(settings: Settings, *, verify: bool = True) -> None:
    set_git_auto_setup_remote()
    ensure_pilot(settings)
    ensure_redis_server()

    current = load_fingerprint(settings)
    desired = desired_fingerprint(settings)
    plan = plan_sync(settings, current, desired)
    for line in plan.describe():
        cprint(line, level=3)
    if plan.is_noop():
        cprint("devctl sync: nothing to do.", level=2)
        if verify:
            verify_installation(settings)
        return

    init_bench_if_not_exist(settings)
    ensure_classic_bench_compat(settings)
    ensure_app_history(settings)

    created_or_installed = False
    if plan.create_sites or plan.install_apps or not current:
        create_sites(settings)
        created_or_installed = True
    else:
        if plan.install_apps:
            app_names = [spec.name for spec in settings.apps()]
            with redis_running(settings):
                for site, missing in plan.install_apps.items():
                    provision_site(settings, site, app_names if missing else [])
        if plan.rebuild_assets:
            ensure_assets_built(settings)

    # Site create/install-app already migrates. Extra migrate is only for app
    # revision changes, and Frappe refuses to migrate without Redis.
    if plan.migrate_sites and not created_or_installed:
        from cohenix_dev.runtime.pilot import run_pilot

        with redis_running(settings):
            for site in plan.migrate_sites:
                cprint(f"Migrating {site} ...", level=2)
                run_pilot(settings, "--bench", settings.bench_name, "frappe", "--site", site, "migrate")

    if verify:
        verify_installation(settings)
    write_provisioning_record(settings)
    desired = desired_fingerprint(settings)
    save_fingerprint(settings, desired)
    cprint("devctl sync complete.", level=2)
