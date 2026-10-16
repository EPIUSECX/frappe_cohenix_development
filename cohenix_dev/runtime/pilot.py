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
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, NamedTuple

from cohenix_dev.config import (
    ADMIN_DEPS_FALLBACK,
    BENCH_SHIM_LEGACY_MARKERS,
    BENCH_SHIM_MARKER,
    PILOT_CLI_DEPS,
    PILOT_RELEASE_DOWNLOAD_URL,
    PILOT_RELEASES_URL,
    PILOT_SHIM_MARKER,
    Settings,
    load_checksums,
    load_toolchain,
)
from cohenix_dev.errors import CohenixError, ConfigError
from cohenix_dev.output import cprint
from cohenix_dev.util import python3, run_command, which

_PILOT_TAG = re.compile(r"v?[0-9A-Za-z][0-9A-Za-z._+-]*")
_RELEASE_CACHE = ".cohenix-release.json"
_KEEP_ON_UPGRADE = frozenset({"benches"})


class PilotRelease(NamedTuple):
    version: str
    url: str
    sha256: str | None = None
    etag: str | None = None


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


def pilot_release_from_payload(releases: list[dict[str, Any]]) -> PilotRelease:
    """Pick the newest published release that ships ``pilot.tar.gz``.

    GitHub returns releases newest first. Pre-releases are included: every
    Pilot tag published so far is a pre-release, and ``/releases/latest``
    skips those.
    """
    for release in releases:
        if release.get("draft"):
            continue
        for asset in release.get("assets") or []:
            if asset.get("name") != "pilot.tar.gz":
                continue
            digest = str(asset.get("digest") or "")
            sha256 = digest.split(":", 1)[1] if digest.startswith("sha256:") else None
            return PilotRelease(
                version=str(release["tag_name"]),
                url=str(asset["browser_download_url"]),
                sha256=sha256,
            )
    raise CohenixError("No pilot.tar.gz release asset found")


def _github_headers(etag: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "cohenix-dev",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if etag:
        headers["If-None-Match"] = etag
    return headers


def github_releases(etag: str | None = None) -> tuple[int, str | None, bytes]:
    """GET the Pilot releases list. A 304 means the cached release is current.

    Conditional 304 responses do not spend the GitHub rate limit.
    """
    request = urllib.request.Request(PILOT_RELEASES_URL, headers=_github_headers(etag))
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return response.status, response.headers.get("ETag"), response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, etag, b""
        detail = exc.read().decode(errors="replace")[:300]
        raise CohenixError(f"GitHub release check failed ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise CohenixError(f"GitHub release check failed: {exc.reason}") from exc


def _release_cache_path(root: Path) -> Path:
    return root / _RELEASE_CACHE


def _read_release_cache(root: Path) -> dict[str, Any] | None:
    path = _release_cache_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_release_cache(root: Path, release: PilotRelease) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "etag": release.etag,
        "sha256": release.sha256,
        "url": release.url,
        "version": release.version,
    }
    _release_cache_path(root).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _release_from_cache(cache: dict[str, Any], etag: str | None) -> PilotRelease:
    version = cache.get("version")
    url = cache.get("url")
    if not version or not url:
        raise CohenixError("Cached Pilot release is incomplete")
    sha256 = cache.get("sha256") or None
    return PilotRelease(str(version), str(url), str(sha256) if sha256 else None, etag)


def resolve_latest_pilot_release(root: Path) -> PilotRelease:
    """Resolve the newest Pilot release, reusing a cached ETag when it has not changed."""
    cache = _read_release_cache(root)
    try:
        status, etag, body = github_releases(str(cache.get("etag")) if cache and cache.get("etag") else None)
    except CohenixError:
        if cache and cache.get("version") and cache.get("url"):
            cprint(
                f"GitHub release check failed; using the last resolved release {cache['version']}.",
                level=3,
            )
            return _release_from_cache(cache, str(cache.get("etag")) if cache.get("etag") else None)
        raise
    if status == 304:
        if not cache:
            raise CohenixError("GitHub reported no change, but no cached Pilot release is recorded")
        return _release_from_cache(cache, etag)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise CohenixError("GitHub release check returned invalid JSON") from exc
    if not isinstance(payload, list):
        raise CohenixError("GitHub release check returned an unexpected payload")
    parsed = pilot_release_from_payload(payload)
    release = PilotRelease(parsed.version, parsed.url, parsed.sha256, etag)
    _write_release_cache(root, release)
    return release


def latest_pilot_release() -> tuple[str, str]:
    status, _etag, body = github_releases(None)
    if status == 304 or not body:
        raise CohenixError("GitHub release check returned no release list")
    release = pilot_release_from_payload(json.loads(body))
    return release.version, release.url


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
    toolchain = load_toolchain().get("pilot") or {}
    if version == toolchain.get("version"):
        digest = toolchain.get("sha256")
        return str(digest) if digest else None
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


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path)


def replace_pilot_tree(archive: Path, root: Path) -> None:
    """Extract a release over ``root``, leaving ``benches/`` in place."""
    staging = Path(tempfile.mkdtemp(prefix="pilot-release-"))
    try:
        extract_pilot_tarball(archive, staging)
        root.mkdir(parents=True, exist_ok=True)
        for child in list(root.iterdir()):
            if child.name in _KEEP_ON_UPGRADE:
                continue
            _remove_path(child)
        for child in staging.iterdir():
            if child.name in _KEEP_ON_UPGRADE:
                continue
            shutil.move(str(child), root / child.name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _verify_archive(settings: Settings, release: PilotRelease, archive: Path) -> None:
    expected = release.sha256 or expected_pilot_sha256(release.version)
    if settings.pilot_version == "latest" and not expected:
        raise CohenixError(f"Pilot {release.version} did not publish a sha256 digest; not installing it.")
    if not expected:
        cprint(
            f"No recorded SHA256 for Pilot {release.version}; skipping checksum verification.",
            level=3,
        )
        return
    actual = _sha256(archive)
    if actual != expected:
        raise CohenixError(f"Pilot {release.version} checksum mismatch: expected {expected}, got {actual}")


def _install_pilot_release(settings: Settings, release: PilotRelease) -> None:
    root = pilot_dir(settings)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as handle:
        tmp = Path(handle.name)
    try:
        download_pilot_tarball(release.url, tmp)
        _verify_archive(settings, release, tmp)
        replace_pilot_tree(tmp, root)
    finally:
        tmp.unlink(missing_ok=True)
    executable = root / "bin" / "pilot"
    if not executable.is_file():
        raise FileNotFoundError(f"Pilot installation missing executable: {executable}")
    bench_link = root / "bench"
    if bench_link.is_symlink() or bench_link.exists():
        bench_link.unlink()
    bench_link.symlink_to(executable)
    bench_link.chmod(0o755)
    if settings.pilot_version == "latest":
        _write_release_cache(root, release)


def _stop_running_bench(settings: Settings) -> None:
    from cohenix_dev.runtime.processes import read_pid, stop_bench

    if read_pid(settings) is None:
        return
    cprint(f"Stopping bench {settings.bench_name} before updating Pilot.", level=2)
    stop_bench(settings)


def _pilot_release_for(settings: Settings) -> PilotRelease | None:
    """Return a release that still needs installing, or None when the tree is current."""
    root = pilot_dir(settings)
    installed = installed_pilot_version(settings) if pilot_bin(settings).is_file() else ""
    if settings.pilot_version == "latest":
        try:
            release = resolve_latest_pilot_release(root)
        except CohenixError as exc:
            if installed:
                cprint(f"{exc}. Keeping Pilot {installed}.", level=3)
                return None
            raise
        return None if installed == release.version else release
    try:
        version, url = pilot_release_asset(settings.pilot_version)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    if installed and installed != version:
        raise CohenixError(
            f"Pilot version mismatch: requested {settings.pilot_version}, found {installed}. "
            f"Remove {root} to replace a frozen release, or unset PILOT_VERSION to track the newest release."
        )
    if installed == version:
        return None
    return PilotRelease(version, url, expected_pilot_sha256(version))


def ensure_pilot(settings: Settings) -> None:
    """Install or update the Pilot release tarball.

    ``latest`` follows the newest GitHub release, including pre-releases, on
    every sync. An explicit ``PILOT_VERSION`` tag stays frozen. Existing
    benches are kept. ``install.sh`` is not used: it installs MariaDB, nginx,
    and supervisor and would shadow frappe/bench.
    """
    release = _pilot_release_for(settings)
    if release is None:
        cprint(f"Pilot {installed_pilot_version(settings)} is current", level=3)
    else:
        previous = installed_pilot_version(settings) if pilot_bin(settings).is_file() else ""
        if previous:
            cprint(f"Updating Pilot {previous} to {release.version} ...", level=2)
            _stop_running_bench(settings)
        else:
            cprint(f"Installing Pilot {release.version} into {pilot_dir(settings)} ...", level=2)
        _install_pilot_release(settings, release)
        cprint(f"Pilot {installed_pilot_version(settings)} installed", level=2)

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
    """Expose `pilot` on PATH and wrap mutating commands so workers reload."""
    link = Path.home() / ".local" / "bin" / "pilot"
    link.parent.mkdir(parents=True, exist_ok=True)
    target = pilot_bin(settings)
    if not target.exists():
        return
    text = link.read_text(errors="ignore") if link.is_file() and not link.is_symlink() else ""
    if PILOT_SHIM_MARKER in text and f'REAL="{target}"' in text:
        return
    if link.is_symlink() or link.exists():
        link.unlink()
    from cohenix_dev.runtime.reload import render_pilot_shim

    link.write_text(render_pilot_shim(target, python3(), PILOT_SHIM_MARKER), encoding="utf-8")
    link.chmod(0o755)
    cprint(f"Pilot available as `pilot` ({link} wraps {target})", level=3)


def ensure_bench_start_shim() -> None:
    """Wrap `bench` so start/stop/restart talk to Pilot and installs reload workers."""
    from cohenix_dev.runtime.reload import render_bench_shim

    locations: list[Path] = []
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        locations.append(Path(venv) / "bin")
    locations.append(Path.home() / ".local" / "bin")
    wrapped = 0
    python = python3()
    for bin_dir in locations:
        wrapper = bin_dir / "bench"
        if not wrapper.exists() and not (bin_dir / "bench.frappe").exists():
            continue
        bin_dir.mkdir(parents=True, exist_ok=True)
        real = bin_dir / "bench.frappe"
        current = wrapper.read_text(errors="ignore") if wrapper.is_file() else ""
        if BENCH_SHIM_MARKER in current and f'REAL="{real}"' in current:
            wrapped += 1
            continue
        if wrapper.exists() and not real.exists():
            if any(marker in current for marker in BENCH_SHIM_LEGACY_MARKERS) or BENCH_SHIM_MARKER in current:
                # v1/broken shim still needs the original console script beside it.
                cprint(f"Replacing outdated bench shim at {wrapper}", level=3)
            else:
                wrapper.rename(real)
        if not real.exists():
            continue
        wrapper.write_text(render_bench_shim(real, python, BENCH_SHIM_MARKER), encoding="utf-8")
        wrapper.chmod(0o755)
        wrapped += 1
        cprint(f"`bench` delegates lifecycle and post-install reload to Pilot ({wrapper})", level=3)
    if not wrapped:
        cprint("No frappe/bench console-script found to wrap, skipping bench shim", level=3)


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


def run_pilot(
    settings: Settings,
    *cli_args: Any,
    cwd: str | Path | None = None,
    reload_after: bool | None = None,
) -> None:
    # Invoke with the venv interpreter so Pilot's `#!/usr/bin/env python3`
    # shebang cannot pick up a broken ~/.local/bin/python3 symlink.
    # This path uses PILOT_DIR/bin/pilot (not the PATH wrapper), so mutating
    # commands must request a worker reload themselves.
    command = [python3(), str(pilot_bin(settings))]
    if settings.verbose:
        command.append("--verbose")
    command += [str(a) for a in cli_args]
    run_command(command, cwd=cwd or str(pilot_dir(settings)), env=bench_subprocess_env(settings))
    if reload_after is None:
        from cohenix_dev.runtime.reload import should_reload_after

        reload_after = should_reload_after([str(a) for a in cli_args])
    if reload_after:
        from cohenix_dev.runtime.reload import reload_bench_workers

        reload_bench_workers(settings)


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
