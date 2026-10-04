"""Site provisioning and incomplete-site recovery."""

from __future__ import annotations

import json

from cohenix_dev.config import Settings
from cohenix_dev.output import cprint
from cohenix_dev.provisioning.apps import apps_for_bench
from cohenix_dev.provisioning.assets import ensure_assets_built
from cohenix_dev.provisioning.bench import set_common_site_config
from cohenix_dev.runtime.database import repair_db_login_scope
from cohenix_dev.runtime.pilot import bench_root, import_pilot_config, run_pilot
from cohenix_dev.runtime.processes import redis_running


def site_installed_apps(settings: Settings, site_name: str) -> list[str]:
    path = bench_root(settings) / "sites" / site_name / "site_config.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("installed_apps", [])


def provision_site(settings: Settings, site_name: str, app_names: list[str]) -> None:
    if (bench_root(settings) / "sites" / site_name).exists():
        missing = [name for name in app_names if name not in site_installed_apps(settings, site_name)]
        if not missing:
            cprint(f"Site {site_name} already exists with all apps, skipping creation", level=3)
        else:
            cprint(
                f"Site {site_name} exists but is missing {', '.join(missing)}; "
                "installing (a previous run must have failed partway)",
                level=3,
            )
            run_pilot(settings, "--bench", settings.bench_name, "install-app", site_name, *missing)
    else:
        cprint(f"Creating Site {site_name} ...", level=2)
        run_pilot(
            settings,
            "--bench",
            settings.bench_name,
            "new-site",
            site_name,
            "--admin-password",
            settings.admin_password,
            "--apps",
            *app_names,
        )
    repair_db_login_scope(settings, site_name)
    for key, value in (("developer_mode", "1"), ("allow_tests", "1")):
        cprint(f"Set {key} on {site_name}", level=3)
        run_pilot(
            settings,
            "--bench",
            settings.bench_name,
            "frappe",
            "--site",
            site_name,
            "set-config",
            key,
            value,
        )


def create_sites(settings: Settings) -> None:
    app_names = [spec.name for spec in apps_for_bench(settings)]
    with redis_running(settings):
        for site_name in settings.site_names():
            provision_site(settings, site_name, app_names)
        set_common_site_config(settings, {"default_site": settings.site_name, "serve_default_site": True})
    ensure_assets_built(settings)
    report_next_steps(settings)


def report_next_steps(settings: Settings) -> None:
    _, bench_config = import_pilot_config(settings)
    config = bench_config.read(bench_root(settings))
    sites = settings.site_names()
    cprint("\nBench ready.", level=2)
    cprint(f"  start:    devctl start", level=2)
    cprint("            (the Dev Container postStartCommand does this for you)", level=3)
    cprint(f"  default:  http://localhost:{config.http_port}  ({settings.site_name})", level=2)
    for site in sites:
        cprint(f"  site:     http://{site}:{config.http_port}/app", level=2)
    cprint(f"  admin UI: http://localhost:{config.admin.port}", level=2)
    cprint(f"  bench cmds: cd {settings.workspace}/{settings.bench_name}", level=2)
    unresolvable = [site for site in sites if not site.endswith(".localhost")]
    if unresolvable:
        entries = "\n".join(f'  echo "127.0.0.1 {site}" | sudo tee -a /etc/hosts' for site in unresolvable)
        cprint(
            f"\nPilot links sites as http://<site>:{config.http_port}/desk, and only the"
            f"\ndefault site answers on plain localhost. For {', '.join(unresolvable)} to"
            f"\nresolve, run this on your host machine (not in the container):\n{entries}"
            f"\n\nNaming sites '<something>.localhost' avoids this entirely.",
            level=3,
        )
