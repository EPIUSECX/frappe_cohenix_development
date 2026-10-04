"""Idempotent environment sync."""

from __future__ import annotations

from cohenix_dev.config import Settings
from cohenix_dev.output import cprint
from cohenix_dev.progress import SYNC_STAGES, StageReporter, environment_rows
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
    reporter = StageReporter("devctl sync", SYNC_STAGES)
    reporter.header(environment_rows(settings))
    try:
        _sync_environment(settings, reporter, verify=verify)
    except Exception:
        reporter.summary()
        raise
    reporter.summary()


def _sync_environment(settings: Settings, reporter: StageReporter, *, verify: bool) -> None:
    set_git_auto_setup_remote()
    with reporter.stage("Install Pilot and Redis"):
        ensure_pilot(settings)
        ensure_redis_server()

    with reporter.stage("Compare fingerprint"):
        current = load_fingerprint(settings)
        desired = desired_fingerprint(settings)
        plan = plan_sync(settings, current, desired)
        for line in plan.describe():
            cprint(line, level=3)

    if plan.is_noop():
        cprint("devctl sync: nothing to do.", level=2)
        reporter.skip_rest("nothing to do", keep=("Verify environment",))
        with reporter.stage("Verify environment", skip=not verify) as running:
            if running:
                verify_installation(settings)
        return

    with reporter.stage("Initialize bench"):
        init_bench_if_not_exist(settings)
    with reporter.stage("Classic Bench compatibility"):
        ensure_classic_bench_compat(settings)
    with reporter.stage("Deepen app history", skip=not plan.deepen_history) as running:
        if running:
            ensure_app_history(settings)

    created_or_installed = False
    need_sites = bool(plan.create_sites or plan.install_apps or not current)
    with reporter.stage("Create sites and install apps", skip=not need_sites) as running:
        if running:
            create_sites(settings)
            created_or_installed = True
        elif plan.install_apps:
            app_names = [spec.name for spec in settings.apps()]
            with redis_running(settings):
                for site, missing in plan.install_apps.items():
                    provision_site(settings, site, app_names if missing else [])

    with reporter.stage(
        "Build assets",
        skip=created_or_installed or not plan.rebuild_assets,
    ) as running:
        if running:
            ensure_assets_built(settings)

    # Site create/install-app already migrates. Extra migrate is only for app
    # revision changes, and Frappe refuses to migrate without Redis.
    should_migrate = bool(plan.migrate_sites and not created_or_installed)
    with reporter.stage("Migrate sites", skip=not should_migrate) as running:
        if running:
            from cohenix_dev.runtime.pilot import run_pilot

            with redis_running(settings):
                for site in plan.migrate_sites:
                    cprint(f"Migrating {site} ...", level=2)
                    run_pilot(settings, "--bench", settings.bench_name, "frappe", "--site", site, "migrate")

    with reporter.stage("Verify environment", skip=not verify) as running:
        if running:
            verify_installation(settings)
    with reporter.stage("Save fingerprint"):
        write_provisioning_record(settings)
        desired = desired_fingerprint(settings)
        save_fingerprint(settings, desired)
        cprint("devctl sync complete.", level=2)
