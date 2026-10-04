"""Classic frappe/bench compatibility helpers for a Pilot bench."""

from __future__ import annotations

from pathlib import Path

from cohenix_dev.config import Settings
from cohenix_dev.output import cprint
from cohenix_dev.runtime.pilot import bench_root


def ensure_classic_bench_compat(settings: Settings) -> None:
    """Let frappe/bench 5.x commands run inside a Pilot bench.

    is_bench_directory() requires all of ('apps', 'sites', 'config', 'logs',
    'config/pids'). Pilot keeps pid files in a top-level pids/.
    """
    pids = bench_root(settings) / "config" / "pids"
    if pids.is_dir():
        return
    if not (bench_root(settings) / "bench.toml").exists():
        return
    pids.mkdir(parents=True, exist_ok=True)
    cprint(f"Created {pids} so frappe/bench commands work in the bench directory", level=3)


def classic_bench_python(settings: Settings) -> Path:
    return bench_root(settings) / "env" / "bin" / "python"
