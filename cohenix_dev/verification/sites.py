"""Site configuration verification."""

from __future__ import annotations

import json

from cohenix_dev.config import Settings
from cohenix_dev.runtime.pilot import bench_root


def site_config_errors(settings: Settings) -> list[str]:
    root = bench_root(settings)
    if not (root / "sites").exists():
        return ["sites directory is missing"]
    errors: list[str] = []
    common = root / "sites" / "common_site_config.json"
    if common.exists():
        data = json.loads(common.read_text(encoding="utf-8"))
        if not data.get("serve_default_site"):
            errors.append("serve_default_site is not enabled; http://localhost will 404")
        if data.get("default_site") != settings.site_name:
            errors.append(
                f"default_site is {data.get('default_site')!r}, expected {settings.site_name!r}"
            )
    else:
        errors.append("sites/common_site_config.json is missing")
    for site in settings.site_names():
        path = root / "sites" / site / "site_config.json"
        if not path.exists():
            errors.append(f"{site}: site_config.json is missing")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data.get("db_name"):
            errors.append(f"{site}: db_name is missing")
        if not site.endswith(".localhost"):
            errors.append(f"{site}: name is not a .localhost host; browsers need a hosts-file entry")
    return errors
