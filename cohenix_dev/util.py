"""Small subprocess and filesystem helpers."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from cohenix_dev.errors import CohenixError
from cohenix_dev.output import cprint


def which(name: str) -> str | None:
    return shutil.which(name)


def command_output(*command: str) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def run_command(
    command: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(command),
            cwd=str(cwd) if cwd else None,
            env=env,
            check=check,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        cprint(f"Command failed: {' '.join(map(str, command))}", level=1)
        if check:
            raise CohenixError(f"Command failed: {' '.join(map(str, command))}") from exc
        return subprocess.CompletedProcess(list(command), exc.returncode)


def port_is_live(port: int, host: str = "127.0.0.1", timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def python3() -> str:
    return shutil.which("python3") or sys.executable


def prepend_path(env: dict[str, str], *parts: str | Path) -> dict[str, str]:
    extra = [str(p) for p in parts if p]
    env["PATH"] = os.pathsep.join([*extra, env.get("PATH", "")])
    return env
