"""Bench-directory verification helpers."""

from __future__ import annotations

from pathlib import Path

from cohenix_dev.config import Settings
from cohenix_dev.runtime.pilot import bench_root


def bench_layout_errors(settings: Settings) -> list[str]:
    root = bench_root(settings)
    if not root.exists():
        return [f"bench directory is missing: {root}"]
    errors: list[str] = []
    for name in ("apps", "sites", "config", "logs"):
        if not (root / name).exists():
            errors.append(f"bench directory missing: {name}")
    if not (root / "config" / "pids").is_dir():
        errors.append("config/pids is missing (classic bench commands will refuse to run)")
    if not (root / "config" / "redis_cache.conf").exists():
        errors.append("Redis cache config is missing")
    if not (root / "env" / "bin" / "python").exists():
        errors.append("bench Python environment is missing or incomplete")
    return errors


def apps_txt(settings: Settings) -> list[str]:
    path = bench_root(settings) / "sites" / "apps.txt"
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
