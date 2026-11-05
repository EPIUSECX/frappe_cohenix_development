#!/usr/bin/env python3
"""Resolve config/profiles.toml into a JSON app list for native WSL provisioning."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


ALLOWED_PROFILES = frozenset(
    {"frappe", "erp", "hr", "localisation", "integrations", "full-cohenix"}
)


def load_profiles(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def resolve(name: str, doc: dict, default_branch: str = "version-16") -> list[dict[str, str]]:
    if name not in ALLOWED_PROFILES:
        raise SystemExit(f"Profile not allowlisted: {name}")
    profiles = doc.get("profiles") or {}
    if name not in profiles:
        raise SystemExit(f"Unknown profile: {name}")

    def walk(profile_name: str, seen: set[str]) -> list[dict[str, str]]:
        if profile_name in seen:
            raise SystemExit(f"Profile cycle involving {profile_name}")
        seen.add(profile_name)
        profile = profiles[profile_name]
        apps: list[dict[str, str]] = []
        parent = profile.get("extends")
        if parent:
            apps.extend(walk(str(parent), seen))
        by_name = {app["name"]: i for i, app in enumerate(apps)}
        for raw in profile.get("apps") or []:
            repo = str(raw.get("repo") or raw.get("url") or "")
            if not repo.startswith("https://"):
                raise SystemExit(f"Refusing non-https app repo: {repo!r}")
            app_name = str(raw.get("name") or repo.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git"))
            branch = str(raw.get("branch") or default_branch)
            entry = {"name": app_name, "repo": repo, "branch": branch}
            if app_name in by_name:
                apps[by_name[app_name]] = entry
            else:
                by_name[app_name] = len(apps)
                apps.append(entry)
        return apps

    return walk(name, set())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--default-branch", default="version-16")
    parser.add_argument("--toml-apps", action="store_true", help="Emit [[apps]] TOML fragments")
    args = parser.parse_args()
    doc = load_profiles(args.profiles)
    apps = resolve(args.profile, doc, args.default_branch)
    if args.toml_apps:
        for app in apps:
            sys.stdout.write(
                "[[apps]]\n"
                f'name = "{app["name"]}"\n'
                f'repo = "{app["repo"]}"\n'
                f'branch = "{app["branch"]}"\n\n'
            )
        return
    json.dump({"profile": args.profile, "apps": apps}, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
