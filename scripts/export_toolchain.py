#!/usr/bin/env python3
"""Print toolchain values as KEY=value for GitHub Actions and Compose."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    print("Python 3.11+ is required to read toolchain.toml", file=sys.stderr)
    raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-output", action="store_true")
    parser.add_argument("--exports", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    data = tomllib.loads((root / "toolchain.toml").read_text(encoding="utf-8"))
    values = {
        "PYTHON_VERSION": data["python"]["version"],
        "NODE_VERSION": data["node"]["version"],
        "YARN_VERSION": data["node"]["yarn"],
        "UV_VERSION": data["uv"]["version"],
        "PILOT_VERSION": data["pilot"]["version"],
        "PILOT_CANARY_VERSION": data["pilot"]["canary_version"],
        "PILOT_SHA256": data["pilot"]["sha256"],
        "PILOT_CANARY_SHA256": data["pilot"]["canary_sha256"],
        "BENCH_REF": data["bench"]["ref"],
        "FRAPPE_BRANCH": data["frappe"]["branch"],
        "MARIADB_IMAGE": data["database"]["mariadb_image"],
        "POSTGRES_IMAGE": data["database"]["postgres_image"],
        "MAILPIT_IMAGE": data["optional"]["mailpit_image"],
        "REDIS_IMAGE": data["optional"]["redis_image"],
        "CYPRESS_IMAGE": data["optional"]["cypress_image"],
        "IMAGE_NAME": f"{data['image']['registry']}/{data['image']['name']}",
        "IMAGE_TAG": data["image"]["tag"],
        "DEV_IMAGE_TAG": data["image"]["tag"],
        "COHENIX_PROFILE": data["defaults"]["profile"],
        "SITE_NAME": data["defaults"]["site_name"],
        "BENCH_NAME": data["defaults"]["bench_name"],
    }
    if args.github_output:
        dest = Path(__import__("os").environ["GITHUB_OUTPUT"])
        with dest.open("a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={value}\n")
        return 0
    prefix = "export " if args.exports else ""
    for key, value in values.items():
        print(f"{prefix}{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
