"""Pilot install, PATH, CLI dependencies, and process wrapper."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from cohenix_dev.config import (
    ADMIN_DEPS_FALLBACK,
    BENCH_SHIM_MARKER,
    PILOT_CLI_DEPS,
    PILOT_RELEASE_DOWNLOAD_URL,
    PILOT_RELEASES_URL,
    Settings,
    load_checksums,
    load_toolchain,
)
from cohenix_dev.errors import CohenixError, ConfigError
from cohenix_dev.output import cprint
from cohenix_dev.util import python3, run_command, which

_PILOT_TAG = re.compile(r"v?[0-9A-Za-z][0-9A-Za-z._+-]*")


def pilot_dir(settings: Settings) -> Path:
    return Path(settings.pilot_dir)


def benches_dir(settings: Settings) -> Path:
    return pilot_dir(settings) / "benches"


def bench_root(settings: Settings) -> Path:
    return benches_dir(settings) / settings.bench_name


def pilot_bin(settings: Settings) -> Path:
    return pilot_dir(settings) / "bin" / "pilot"


def installed_pilot_version(settings: Settings | object) -> str:
    directory = Path(getattr(settings, "pilot_dir"))
    version_file = directory / "VERSION"
    return version_file.read_text(encoding="utf-8").strip() if version_file.exists() else "unknown"


def latest_pilot_release() -> tuple[str, str]:
    with urllib.request.urlopen(PILOT_RELEASES_URL, timeout=60) as response:  # noqa: S310
        releases = json.load(response)
    for release in releases:
        for asset in release.get("assets", []):
            if asset.get("name") == "pilot.tar.gz":
                return release["tag_name"], asset["browser_download_url"]
    raise CohenixError("No pilot.tar.gz release asset found")


def canary_pilot_release() -> str:
    return str(load_toolchain()["pilot"]["canary_version"])


def pilot_release_asset(version: str) -> tuple[str, str]:
    if version == "latest":
        return latest_pilot_release()
    if not _PILOT_TAG.fullmatch(version):
        raise ValueError(f"Invalid Pilot release tag: {version!r}")
    encoded = urllib.parse.quote(version, safe="")
    return version, PILOT_RELEASE_DOWNLOAD_URL.format(version=encoded)


def expected_pilot_sha256(version: str) -> str | None:
    checksums = load_checksums()
    table = checksums.get("pilot") or {}
    if version in table:
        return str(table[version])
    toolchain = load_toolchain()["pilot"]
    if version == toolchain.get("version"):
        return str(toolchain.get("sha256") or "") or None
    if version == toolchain.get("canary_version"):
        return str(toolchain.get("canary_sha256") or "") or None
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_pilot_tarball(url: str, dest: Path) -> None:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            if which("curl"):
                run_command(
                    [
                        "curl",
                        "-fL",
                        "--retry",
                        "3",
                        "--retry-delay",
                        "2",
                        "--connect-timeout",
                        "30",
                        "--max-time",
                        "300",
                        "-o",
                        str(dest),
                        url,
                    ]
                )
            else:
                with urllib.request.urlopen(url, timeout=300) as response, dest.open("wb") as out:  # noqa: S310
                    shutil.copyfileobj(response, out)
            if dest.stat().st_size > 0:
                return
            raise CohenixError(f"Downloaded empty Pilot archive from {url}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            cprint(f"Pilot download attempt {attempt} failed: {exc}", level=3)
            dest.unlink(missing_ok=True)
    raise CohenixError(f"Could not download Pilot from {url}: {last_error}") from last_error


def extract_pilot_tarball(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as handle:
        handle.extractall(dest, filter="data")


def ensure_pilot(settings: Settings) -> None:
    """Install the requested Pilot release tarball if it is not there yet.

    Deliberately not install.sh: that script installs MariaDB, PostgreSQL,
    nginx, supervisor and certbot system-wide and prepends its own `bench` to
    PATH, which would shadow frappe/bench 5.x in this image.
    """
    root = pilot_dir(settings)
    if not pilot_bin(settings).exists():
        try:
            version, url = pilot_release_asset(settings.pilot_version)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        cprint(f"Installing Pilot {version} into {root} ...", level=2)
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as handle:
            tmp = Path(handle.name)
        try:
            download_pilot_tarball(url, tmp)
            expected = expected_pilot_sha256(version)
            if expected:
                actual = _sha256(tmp)
                if actual != expected:
                    raise CohenixError(
                        f"Pilot {version} checksum mismatch: expected {expected}, got {actual}"
                    )
            else:
                cprint(
                    f"No recorded SHA256 for Pilot {version}; skipping checksum verification.",
                    level=3,
                )
            extract_pilot_tarball(tmp, root)
        finally:
            tmp.unlink(missing_ok=True)
        executable = root / "bin" / "pilot"
        bench_link = root / "bench"
        if not bench_link.exists():
            if executable.exists():
                bench_link.symlink_to(executable)
            else:
                raise FileNotFoundError(f"Pilot installation missing executable: {executable}")
        bench_link.chmod(0o755)
        cprint(f"Pilot {installed_pilot_version(settings)} installed", level=2)
    else:
        installed = installed_pilot_version(settings)
        if settings.pilot_version != "latest" and installed != settings.pilot_version:
            raise CohenixError(
                f"Pilot version mismatch: requested {settings.pilot_version}, found {installed}. "
                f"Remove {root} to perform an intentional clean upgrade, or pass "
                f"--pilot-version {installed}."
            )
        cprint(f"Pilot {installed} already installed", level=3)

    ensure_pilot_cli_deps()
    ensure_admin_venv(settings)
    ensure_pilot_on_path(settings)
    ensure_bench_start_shim()


def pilot_cli_python() -> str:
    return python3()


def ensure_pilot_cli_deps() -> None:
    python = pilot_cli_python()
    import subprocess

    probe = subprocess.run(
        [
            python,
            "-c",
            "import importlib.util as u,sys;"
            "print(' '.join(m for m in sys.argv[1:] if u.find_spec(m) is None))",
            *PILOT_CLI_DEPS,
        ],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        raise CohenixError(f"Could not probe {python} for Pilot's CLI dependencies:\n{probe.stderr}")
    missing = probe.stdout.split()
    if not missing:
        return
    cprint(f"Installing Pilot CLI dependencies into {python}: {', '.join(missing)}", level=2)
    run_command(
        [python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", *missing],
        env=bench_subprocess_env(),
    )


def admin_deps(settings: Settings) -> list[str]:
    pyproject = pilot_dir(settings) / "pyproject.toml"
    if not pyproject.exists():
        return list(ADMIN_DEPS_FALLBACK)
    with pyproject.open("rb") as handle:
        data = __import__("tomllib").load(handle)
    extras = data.get("project", {}).get("optional-dependencies", {})
    return extras.get("admin") or list(ADMIN_DEPS_FALLBACK)


def ensure_admin_venv(settings: Settings) -> None:
    venv = pilot_dir(settings) / ".admin-venv"
    if (venv / "bin" / "flask").exists():
        return
    deps = admin_deps(settings)
    env = bench_subprocess_env(settings)
    cprint("Creating Pilot admin environment ...", level=2)
    run_command(["uv", "venv", str(venv), "--clear", "--quiet"], env=env)
    cprint(f"Installing {len(deps)} admin dependencies (several minutes) ...", level=2)
    run_command(["uv", "pip", "install", "--python", str(venv / "bin" / "python"), *deps], env=env)


def ensure_pilot_on_path(settings: Settings) -> None:
    link = Path.home() / ".local" / "bin" / "pilot"
    link.parent.mkdir(parents=True, exist_ok=True)
    target = pilot_bin(settings)
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target)
    cprint(f"Pilot available as `pilot` ({link} -> {target})", level=3)


def ensure_bench_start_shim() -> None:
    """Make `bench start` call Pilot. Wrap the venv console script when present."""
    locations: list[Path] = []
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        locations.append(Path(venv) / "bin")
    locations.append(Path.home() / ".local" / "bin")
    for bin_dir in locations:
        wrapper = bin_dir / "bench"
        if not wrapper.exists() and not (bin_dir / "bench.frappe").exists():
            continue
        bin_dir.mkdir(parents=True, exist_ok=True)
        real = bin_dir / "bench.frappe"
        already_shimmed = wrapper.is_file() and BENCH_SHIM_MARKER in wrapper.read_text(errors="ignore")
        if already_shimmed:
            return
        if wrapper.exists() and not real.exists():
            wrapper.rename(real)
        if not real.exists():
            continue
        wrapper.write_text(
            "#!/usr/bin/env bash\n"
            f"{BENCH_SHIM_MARKER}\n"
            'if [ "${1:-}" = "start" ]; then\n'
            "    shift\n"
            '    exec pilot -b "$(basename "$PWD")" start "$@"\n'
            "else\n"
            f'    exec "{real}" "$@"\n'
            "fi\n"
        )
        wrapper.chmod(0o755)
        cprint(f"`bench start` now delegates to Pilot ({wrapper})", level=3)
        return
    cprint("No frappe/bench console-script found to wrap, skipping bench-start shim", level=3)


def bench_subprocess_env(settings: Settings | None = None) -> dict[str, str]:
    env = os.environ.copy()
    path_parts: list[str] = []
    venv = env.get("VIRTUAL_ENV")
    if venv:
        path_parts.append(str(Path(venv) / "bin"))
    path_parts.append(str(Path.home() / ".local" / "bin"))
    if settings is not None and settings.node_version:
        nvm_dir = os.environ.get("NVM_DIR", str(Path.home() / ".nvm"))
        node_bin = Path(nvm_dir) / "versions" / "node" / f"v{settings.node_version}" / "bin"
        if node_bin.is_dir():
            path_parts.insert(0, str(node_bin))
    env["PATH"] = os.pathsep.join([*path_parts, env.get("PATH", "")])
    env.setdefault("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv"))
    env.setdefault("YARN_CACHE_FOLDER", str(Path.home() / ".cache" / "yarn"))
    env.setdefault("npm_config_cache", str(Path.home() / ".npm"))
    if venv:
        env.setdefault("VIRTUAL_ENV", venv)
    return env


def run_pilot(settings: Settings, *cli_args: Any, cwd: str | Path | None = None) -> None:
    # Invoke with the venv interpreter so Pilot's `#!/usr/bin/env python3`
    # shebang cannot pick up a broken ~/.local/bin/python3 symlink.
    command = [python3(), str(pilot_bin(settings))]
    if settings.verbose:
        command.append("--verbose")
    command += [str(a) for a in cli_args]
    run_command(command, cwd=cwd or str(pilot_dir(settings)), env=bench_subprocess_env(settings))


def import_pilot_config(settings: Settings):
    root = str(pilot_dir(settings))
    if root not in sys.path:
        sys.path.insert(0, root)
    from pilot.config import AppConfig, BenchConfig  # noqa: PLC0415

    return AppConfig, BenchConfig


def ensure_redis_server() -> None:
    if which("redis-server") or which("valkey-server"):
        return
    cprint("Installing redis-server (Pilot manages its own Redis) ...", level=2)
    apt_env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    run_command(["sudo", "-n", "apt-get", "update"], env=apt_env)
    run_command(
        ["sudo", "-n", "apt-get", "install", "-y", "--no-install-recommends", "redis-server"],
        env=apt_env,
    )
    import subprocess

    subprocess.run(["sudo", "-n", "service", "redis-server", "stop"], check=False)
