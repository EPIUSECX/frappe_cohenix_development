"""Install an attach-style debugpy listener into the bench Python env.

When enabled, Pilot's web (and other) processes listen on COHENIX_DEBUGPY_PORT
(default 5678) without waiting for a client. Attach from the editor with the
"Frappe: Attach to Pilot web" launch config — no need to stop Pilot or launch
a second web server.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from cohenix_dev.config import Settings
from cohenix_dev.errors import CohenixError
from cohenix_dev.output import cprint
from cohenix_dev.runtime.pilot import bench_root

HOOK_MARKER = "# cohenix-debugpy-hook v1"
DEFAULT_PORT = 5678


def debug_state_path(settings: Settings) -> Path:
    return bench_root(settings) / ".cohenix" / "debugpy.json"


def default_port() -> int:
    raw = os.environ.get("COHENIX_DEBUGPY_PORT", str(DEFAULT_PORT))
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_PORT


def is_enabled(settings: Settings) -> bool:
    path = debug_state_path(settings)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        return bool(data.get("enabled"))
    # Fall back to container/env default so Dev Containers attach out of the box.
    return os.environ.get("COHENIX_DEBUGPY", "0") not in {"", "0", "false", "False", "no", "off"}


def site_packages_dir(settings: Settings) -> Path:
    env = bench_root(settings) / "env"
    candidates = sorted((env / "lib").glob("python*/site-packages"))
    if not candidates:
        raise CohenixError(f"Bench env has no site-packages under {env}")
    return candidates[-1]


def sitecustomize_path(settings: Settings) -> Path:
    return site_packages_dir(settings) / "sitecustomize.py"


def render_sitecustomize(port: int) -> str:
    return (
        f"{HOOK_MARKER}\n"
        "import os\n"
        "import sys\n"
        "\n"
        "def _cohenix_debugpy_listen() -> None:\n"
        "    flag = os.environ.get('COHENIX_DEBUGPY', '1')\n"
        "    if flag in ('', '0', 'false', 'False', 'no', 'off'):\n"
        "        return\n"
        "    # Avoid double-listen in forked children that re-import sitecustomize.\n"
        "    if os.environ.get('COHENIX_DEBUGPY_LISTENING') == '1':\n"
        "        return\n"
        "    try:\n"
        "        import debugpy\n"
        "    except ImportError:\n"
        "        return\n"
        "    try:\n"
        "        if getattr(debugpy, 'is_client_connected', lambda: False)():\n"
        "            return\n"
        f"        port = int(os.environ.get('COHENIX_DEBUGPY_PORT', '{port}'))\n"
        "        debugpy.listen(('0.0.0.0', port))\n"
        "        os.environ['COHENIX_DEBUGPY_LISTENING'] = '1'\n"
        "    except Exception:\n"
        "        # Never break Frappe boot because the debugger failed.\n"
        "        return\n"
        "\n"
        "_cohenix_debugpy_listen()\n"
    )


def ensure_debugpy_package(settings: Settings) -> None:
    python = bench_root(settings) / "env" / "bin" / "python"
    if not python.is_file():
        return
    import subprocess

    probe = subprocess.run(
        [str(python), "-c", "import debugpy"],
        capture_output=True,
        check=False,
        timeout=60,
    )
    if probe.returncode == 0:
        return
    cprint("Installing debugpy into the bench env for attach debugging ...", level=2)
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), "debugpy>=1.8"],
        check=True,
        timeout=300,
    )


def install_hook(settings: Settings, *, port: int | None = None) -> Path:
    ensure_debugpy_package(settings)
    listen_port = port or default_port()
    path = sitecustomize_path(settings)
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        if HOOK_MARKER not in existing and existing.strip():
            raise CohenixError(
                f"{path} already exists and is not managed by Cohenix. "
                "Move it aside, then re-run `devctl debug enable`."
            )
    path.write_text(render_sitecustomize(listen_port), encoding="utf-8")
    return path


def remove_hook(settings: Settings) -> None:
    path = sitecustomize_path(settings)
    if path.is_file() and HOOK_MARKER in path.read_text(encoding="utf-8"):
        path.unlink()
        cprint(f"Removed debugpy sitecustomize at {path}", level=3)


def enable_debugpy(settings: Settings, *, port: int | None = None, reload_workers: bool = True) -> int:
    listen_port = port or default_port()
    path = install_hook(settings, port=listen_port)
    state = debug_state_path(settings)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"enabled": True, "port": listen_port}, indent=2) + "\n", encoding="utf-8")
    os.environ["COHENIX_DEBUGPY"] = "1"
    os.environ["COHENIX_DEBUGPY_PORT"] = str(listen_port)
    cprint(f"debugpy will listen on 0.0.0.0:{listen_port} after the next web reload ({path}).", level=2)
    cprint("Attach with Run and Debug → Frappe: Attach to Pilot web.", level=3)
    if reload_workers:
        from cohenix_dev.runtime.reload import reload_bench_workers

        reload_bench_workers(settings, web_only=True)
    return 0


def disable_debugpy(settings: Settings, *, reload_workers: bool = True) -> int:
    remove_hook(settings)
    state = debug_state_path(settings)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"enabled": False, "port": default_port()}, indent=2) + "\n", encoding="utf-8")
    os.environ["COHENIX_DEBUGPY"] = "0"
    cprint("debugpy attach disabled. Reload web to drop the listener.", level=2)
    if reload_workers:
        from cohenix_dev.runtime.reload import reload_bench_workers

        reload_bench_workers(settings, web_only=True)
    return 0


def debug_status(settings: Settings) -> int:
    enabled = is_enabled(settings)
    port = default_port()
    path = debug_state_path(settings)
    if path.is_file():
        try:
            port = int(json.loads(path.read_text(encoding="utf-8")).get("port") or port)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    hook = sitecustomize_path(settings) if (bench_root(settings) / "env").exists() else None
    cprint(f"debugpy enabled: {enabled}", level=2)
    cprint(f"debugpy port:    {port}", level=3)
    if hook is not None:
        cprint(f"sitecustomize:   {hook} ({'present' if hook.is_file() else 'missing'})", level=3)
    return 0


def ensure_debugpy_for_sync(settings: Settings) -> None:
    """Install the hook when the Dev Container default (or prior enable) asks for it."""
    if not (bench_root(settings) / "env" / "bin" / "python").is_file():
        return
    if not is_enabled(settings):
        return
    install_hook(settings, port=default_port())
