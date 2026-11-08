#!/usr/bin/env python3
"""Re-audit config/pilot-compat.toml against the newest Pilot release.

Downloads the latest pilot.tar.gz (or PILOT_VERSION), checks a few heuristics,
and prints which workarounds look droppable on canary. Does not edit the
manifest — update pilot-compat.toml after confirming with smoke tests.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPAT = ROOT / "config" / "pilot-compat.toml"
RELEASES = "https://api.github.com/repos/frappe/pilot/releases?per_page=5"


def latest_tag() -> str:
    forced = os.environ.get("PILOT_VERSION")
    if forced and forced != "latest":
        return forced
    request = urllib.request.Request(RELEASES, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        releases = json.load(response)
    for release in releases:
        if release.get("draft"):
            continue
        for asset in release.get("assets") or []:
            if asset.get("name") == "pilot.tar.gz":
                return str(release["tag_name"])
    raise SystemExit("No Pilot release with pilot.tar.gz found")


def download_and_extract(tag: str, dest: Path) -> Path:
    url = f"https://github.com/frappe/pilot/releases/download/{tag}/pilot.tar.gz"
    archive = dest / "pilot.tar.gz"
    print(f"Downloading {url}")
    urllib.request.urlretrieve(url, archive)
    with tarfile.open(archive, "r:gz") as handle:
        handle.extractall(dest)
    return dest


def file_text(root: Path, relative: str) -> str:
    path = root / relative
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def heuristics(root: Path) -> dict[str, bool]:
    """True means 'still looks required on this release'."""
    defs = file_text(root, "pilot/managers/processes/definitions.py")
    admin = file_text(root, "pilot/config/admin.py")
    repo = file_text(root, "pilot/core/app/repository.py")
    create = file_text(root, "pilot/commands/sites/create.py") + file_text(
        root, "pilot/core/site/commands.py"
    )
    packaging_vendor = (root / "pilot/_vendor/packaging").is_dir()
    return {
        "cli-packaging": not packaging_vendor,
        "procfile-omits-scheduler": "def schedule_definition" not in defs,
        "port-offset-publish": "port: int = 7000" in admin or "port=data.get(\"port\", 7000)" in admin,
        "shallow-clone-history": '"--depth", "1"' in repo or "'--depth', '1'" in repo or "--depth=1" in repo,
        "db-login-scope": "mariadb-user-host-login-scope" not in create
        and "mariadb_user_host_login_scope" not in create,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=None)
    args = parser.parse_args()
    tag = args.tag or latest_tag()
    import tomllib

    data = tomllib.loads(COMPAT.read_text(encoding="utf-8"))
    print(f"Manifest audited_canary: {data.get('audited_canary')}")
    print(f"Checking Pilot {tag}")
    with tempfile.TemporaryDirectory() as tmp:
        root = download_and_extract(tag, Path(tmp))
        checks = heuristics(root)
    print("\nHeuristic results (True = still required):")
    for key, required in sorted(checks.items()):
        print(f"  {key}: {required}")
    droppable = [key for key, required in checks.items() if not required]
    if droppable:
        print("\nCandidates to mark still_required_on_canary = false:")
        for key in droppable:
            print(f"  - {key}")
        print(f"\nAfter smoke tests, set audited_canary = \"{tag}\" in {COMPAT}")
    else:
        print("\nNo heuristic drop candidates.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
