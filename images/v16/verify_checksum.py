#!/usr/bin/env python3
"""Verify a downloaded file against config/checksums.toml."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: verify_checksum.py <section> <filename>", file=sys.stderr)
        return 2
    section, filename = sys.argv[1], sys.argv[2]
    checksums = tomllib.loads(Path("/tmp/checksums.toml").read_text(encoding="utf-8"))
    expected = (checksums.get(section) or {}).get(filename)
    if not expected:
        print(f"No checksum recorded for {section}/{filename}", file=sys.stderr)
        return 1
    digest = hashlib.sha256()
    with Path(filename).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        print(f"Checksum mismatch for {filename}: expected {expected}, got {actual}", file=sys.stderr)
        return 1
    print(f"Checksum OK for {filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
