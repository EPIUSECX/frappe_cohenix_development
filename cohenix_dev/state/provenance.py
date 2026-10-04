"""Provisioning provenance record (no passwords)."""

from __future__ import annotations

import datetime as dt
import json
import sys

from cohenix_dev.config import PROVISIONER_SCHEMA, Settings, image_ref
from cohenix_dev.output import cprint
from cohenix_dev.provisioning.apps import app_commit, apps_for_bench
from cohenix_dev.runtime.pilot import bench_root, installed_pilot_version
from cohenix_dev.util import command_output, write_text


def write_provisioning_record(settings: Settings) -> None:
    root = bench_root(settings)
    apps = {}
    for spec in apps_for_bench(settings):
        apps[spec.name] = {
            "repo": spec.repo,
            "requested_ref": spec.branch,
            "resolved_commit": app_commit(root / "apps" / spec.name),
        }
    record = {
        "schema_version": PROVISIONER_SCHEMA,
        "verified_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "profile": settings.profile,
        "image": image_ref(),
        "pilot": {
            "requested_release": settings.pilot_version,
            "installed_release": installed_pilot_version(settings),
        },
        "runtime": {
            "python": sys.version.split()[0],
            "node": command_output("node", "--version"),
            "uv": command_output("uv", "--version"),
        },
        "bench": {
            "name": settings.bench_name,
            "frappe_branch": settings.frappe_branch,
            "apps": apps,
            "sites": settings.site_names(),
        },
    }
    path = root / ".provisioning.json"
    write_text(path, json.dumps(record, indent=2, sort_keys=True) + "\n")
    cprint(f"Wrote resolved provisioning record to {path}", level=3)
