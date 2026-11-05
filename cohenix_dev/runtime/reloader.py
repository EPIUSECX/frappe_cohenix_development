"""Make sure the bench env can run Frappe's `--dev` reloader.

Pilot starts `frappe.runner --dev` when `bench.reload_python` is on, and that refuses to start
without `watchdog`. Pilot gets watchdog from `frappe[dev]`, but that extra does not resolve on
Frappe version-16 (`pypika-stubs` wants a PyPI pypika while Frappe pins a git one). Pilot then
installs Frappe without the extra and only prints a warning, leaving a bench that crashes on
start. Install just watchdog when that happens.
"""

from __future__ import annotations

import subprocess
import tomllib

from cohenix_dev.config import Settings
from cohenix_dev.output import cprint
from cohenix_dev.runtime.pilot import bench_root

WATCHDOG_REQUIREMENT = "watchdog~=6.0.0"


def reload_python_enabled(settings: Settings) -> bool:
    """Whether Pilot runs the web process with `--dev`. Pilot's own default is on."""
    path = bench_root(settings) / "bench.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return True
    return bool(data.get("bench", {}).get("reload_python", True))


def watchdog_importable(settings: Settings) -> bool:
    python = bench_root(settings) / "env" / "bin" / "python"
    if not python.is_file():
        return True  # no env yet; nothing to repair, provisioning will create it
    result = subprocess.run(
        [str(python), "-c", "import watchdog"], capture_output=True, check=False, timeout=60
    )
    return result.returncode == 0


def dev_reloader_missing(settings: Settings) -> bool:
    return reload_python_enabled(settings) and not watchdog_importable(settings)


def ensure_dev_reloader(settings: Settings) -> None:
    """Install watchdog into the bench env when `--dev` needs it and it is absent."""
    if not dev_reloader_missing(settings):
        return
    python = bench_root(settings) / "env" / "bin" / "python"
    cprint("watchdog is missing from the bench env (Pilot skipped frappe[dev]); installing it.", level=2)
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), WATCHDOG_REQUIREMENT],
        check=True,
        timeout=300,
    )
