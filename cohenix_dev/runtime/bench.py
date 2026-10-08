"""Classic frappe/bench compatibility helpers for a Pilot bench."""

from __future__ import annotations

import subprocess
from pathlib import Path

from cohenix_dev.config import Settings
from cohenix_dev.output import cprint
from cohenix_dev.runtime.pilot import bench_root, bench_subprocess_env
from cohenix_dev.util import run_command

FRAPPE_TEST_PACKAGES = [
    "hypothesis~=6.77.0",
    "responses==0.23.1",
    "freezegun~=1.5.1",
    "Faker~=18.10.1",
]


def ensure_classic_bench_compat(settings: Settings) -> None:
    """Let frappe/bench 5.x commands run inside a Pilot bench.

    is_bench_directory() requires all of ('apps', 'sites', 'config', 'logs',
    'config/pids'). Pilot keeps pid files in a top-level pids/.
    """
    pids = bench_root(settings) / "config" / "pids"
    if not pids.is_dir() and (bench_root(settings) / "bench.toml").exists():
        pids.mkdir(parents=True, exist_ok=True)
        cprint(f"Created {pids} so frappe/bench commands work in the bench directory", level=3)
    # Top-level pids/ is where Pilot looks for reload.request / bench.pid.
    (bench_root(settings) / "pids").mkdir(parents=True, exist_ok=True)
    ensure_test_dependencies(settings)


def ensure_test_dependencies(settings: Settings) -> None:
    python = classic_bench_python(settings)
    if not python.is_file():
        return
    probe = subprocess.run(
        [str(python), "-c", "import hypothesis, responses, freezegun, faker"],
        capture_output=True,
        check=False,
    )
    if probe.returncode == 0:
        return
    cprint("Installing Frappe test extras into the bench env (hypothesis) ...", level=3)
    run_command(
        ["uv", "pip", "install", "--python", str(python), *FRAPPE_TEST_PACKAGES],
        env=bench_subprocess_env(settings),
    )


def classic_bench_python(settings: Settings) -> Path:
    return bench_root(settings) / "env" / "bin" / "python"
