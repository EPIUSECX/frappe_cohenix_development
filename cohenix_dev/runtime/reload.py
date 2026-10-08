"""Reload Pilot web/workers without a full stop/start.

Classic `bench --site X install-app` is Frappe CLI: it updates the site and
clears Redis cache, then returns. It never restarts processes. Classic
`Bench.reload()` only knows Overmind. Pilot's own `install-app` only
clear-caches. The running `frappe serve` keeps a stale module map / boot, so
Desk shows an AJAX error until someone restarts Pilot.

Pilot already has the right primitive: write `{bench}/pids/reload.request`
(`workload` or `web`). The running supervisor restarts web, Socket.IO, and
workers and leaves Redis, watch, and admin alone. That is what this module
does, and what the `bench` / `pilot` shims invoke after mutating commands.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from cohenix_dev.config import Settings, settings_from_env
from cohenix_dev.output import cprint
from cohenix_dev.runtime.pilot import bench_root, bench_subprocess_env, pilot_bin
from cohenix_dev.util import port_is_live, python3

RELOAD_REQUEST_NAME = "reload.request"
SCOPE_WORKLOAD = "workload"
SCOPE_WEB = "web"

SKIP_RELOAD_ENV = "COHENIX_SKIP_RELOAD"

# Flags that consume the following token. Unknown `--flag value` pairs are also
# skipped when the next token does not look like a command.
FLAGS_WITH_VALUE = frozenset(
    {
        "-b",
        "--bench",
        "--site",
        "-s",
        "--apps",
        "--app",
        "--branch",
        "--repo",
        "--title",
        "--description",
        "--publisher",
        "--email",
        "--license",
        "--admin-password",
        "--mariadb-root-username",
        "--mariadb-root-password",
        "--db-root-password",
        "--db-host",
        "--db-port",
        "--db-type",
        "--http-port",
        "--socketio-port",
        "--profile",
        "--python",
        "--node",
        "--format",
        "--with-app",
    }
)

BOOLEAN_FLAGS = frozenset(
    {
        "--verbose",
        "-v",
        "--help",
        "-h",
        "--version",
        "--force",
        "--yes",
        "-y",
        "--no-backup",
        "--resolve-deps",
        "--skip-assets",
        "--web",
        "--supervisor",
        "--systemd",
        "--no-procfile",
        "--no-backups",
        "--skip-redis-config-generation",
    }
)

MUTATING_COMMANDS = frozenset(
    {
        "install-app",
        "uninstall-app",
        "migrate",
        "get-app",
        "remove-app",
        "new-app",
        "build",
        "clear-cache",
        "clear-website-cache",
        "disable-app",
        "enable-app",
        "restore",
        "partial-restore",
        "drop-site",
        "new-site",
        "set-config",
    }
)

PASSTHROUGH_COMMANDS = frozenset({"frappe"})


def reload_request_path(root: Path) -> Path:
    return root / "pids" / RELOAD_REQUEST_NAME


def supervisor_pid_path(root: Path) -> Path:
    return root / "pids" / "bench.pid"


def write_reload_request(root: Path, *, web_only: bool = False) -> Path:
    """Leave the same IPC file Pilot's ProcessManager.reload_workers() writes."""
    path = reload_request_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SCOPE_WEB if web_only else SCOPE_WORKLOAD, encoding="utf-8")
    return path


def supervisor_is_running(root: Path) -> bool:
    pid_file = supervisor_pid_path(root)
    if not pid_file.is_file():
        return False
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip().splitlines()[0])
    except (ValueError, OSError):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def first_command(argv: Sequence[str], *, flags_with_value: frozenset[str] | None = None) -> str | None:
    """Return the first non-flag token (the CLI verb)."""
    flags = flags_with_value or FLAGS_WITH_VALUE
    i = 0
    n = len(argv)
    while i < n:
        token = argv[i]
        if token == "--":
            i += 1
            continue
        if token.startswith("-"):
            name, _, inline = token.partition("=")
            if inline:
                i += 1
                continue
            if (
                name in BOOLEAN_FLAGS
                or name.startswith("--no-")
                or name.startswith("--skip-")
            ):
                i += 1
                continue
            if name in flags and i + 1 < n:
                i += 2
                continue
            i += 1
            continue
        return token
    return None


def args_after_command(argv: Sequence[str], command: str) -> list[str]:
    try:
        index = list(argv).index(command)
    except ValueError:
        return []
    return list(argv[index + 1 :])


def mutating_command(argv: Sequence[str]) -> str | None:
    """CLI verb that should reload workers, including `frappe <verb>` passthrough."""
    command = first_command(argv)
    if command in PASSTHROUGH_COMMANDS:
        command = first_command(args_after_command(argv, command))
    if command in MUTATING_COMMANDS:
        return command
    return None


def should_reload_after(argv: Sequence[str]) -> bool:
    if os.environ.get(SKIP_RELOAD_ENV):
        return False
    return mutating_command(argv) is not None


def _http_ok(port: int, site_name: str, timeout: float = 3.0) -> bool:
    url = f"http://127.0.0.1:{port}/api/method/frappe.ping"
    request = urllib.request.Request(url, headers={"Host": site_name})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read().decode("utf-8", errors="replace")
            return response.status < 400 and ("pong" in body.lower() or '"message"' in body)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return False


def _http_port(settings: Settings) -> int:
    try:
        from cohenix_dev.runtime.pilot import import_pilot_config

        _, bench_config = import_pilot_config(settings)
        return int(bench_config.read(bench_root(settings)).http_port)
    except Exception:  # noqa: BLE001
        return int(settings.http_port)


def wait_for_reload(
    settings: Settings,
    root: Path,
    *,
    timeout: float = 30.0,
    http_timeout: float = 25.0,
) -> bool:
    """Wait until the supervisor consumes the request and HTTP answers again."""
    path = reload_request_path(root)
    consume_deadline = time.monotonic() + min(8.0, timeout)
    while path.exists() and time.monotonic() < consume_deadline:
        time.sleep(0.1)
    port = _http_port(settings)
    http_deadline = time.monotonic() + http_timeout
    while time.monotonic() < http_deadline:
        if port_is_live(port) and _http_ok(port, settings.site_name):
            return True
        time.sleep(0.3)
    return port_is_live(port)


def reload_bench_workers(
    settings: Settings,
    *,
    web_only: bool = False,
    wait: bool = True,
    timeout: float = 30.0,
) -> bool:
    """Ask the running Pilot supervisor to restart app processes.

    Returns True when a reload was requested. Missing supervisor is a no-op
    (install during `devctl sync` before `devctl start`). Never stops Redis.
    """
    if os.environ.get(SKIP_RELOAD_ENV):
        return False
    root = bench_root(settings)
    if not (root / "bench.toml").is_file():
        return False
    if not supervisor_is_running(root):
        cprint("Pilot is not running; skip worker reload (no full stop/start needed).", level=3)
        return False
    path = write_reload_request(root, web_only=web_only)
    scope = SCOPE_WEB if web_only else SCOPE_WORKLOAD
    cprint(
        f"Asked Pilot to reload {scope} processes via {path} (Redis/watch/admin stay up).",
        level=2,
    )
    if wait:
        if wait_for_reload(settings, root, timeout=timeout):
            cprint("Site HTTP is back after worker reload.", level=3)
        else:
            cprint(
                "Reload requested; HTTP is not answering yet. "
                "Wait a few seconds or run `devctl doctor`.",
                level=3,
            )
    return True


def infer_bench_name(settings: Settings | None = None) -> str:
    cwd = Path.cwd()
    if (cwd / "bench.toml").is_file():
        return cwd.name
    if settings is not None:
        return settings.bench_name
    return os.environ.get("BENCH_NAME") or "development-bench"


def _exec(command: list[str], env: dict[str, str] | None = None) -> int:
    os.execvpe(command[0], command, env or os.environ)
    return 127  # pragma: no cover — exec never returns


def wrap_bench(real: str, argv: Sequence[str]) -> int:
    """Run classic frappe/bench, mapping process lifecycle onto Pilot."""
    settings = settings_from_env({"bench_name": infer_bench_name()})
    command = first_command(argv) or ""
    env = bench_subprocess_env(settings)
    if command == "start":
        extra = args_after_command(argv, "start")
        binary = pilot_bin(settings)
        if not binary.exists():
            cprint(f"Pilot is not installed at {binary}; run `devctl sync` first.", level=1)
            return 1
        return _exec(
            [python3(), str(binary), "-b", settings.bench_name, "start", *extra],
            env=env,
        )
    if command == "stop":
        from cohenix_dev.runtime.processes import stop_bench

        stop_bench(settings)
        return 0
    if command in {"restart", "reload"}:
        web_only = "--web" in argv
        reload_bench_workers(settings, web_only=web_only)
        return 0
    completed = subprocess.run([real, *argv], env=env, check=False)
    if completed.returncode == 0 and should_reload_after(argv):
        reload_bench_workers(settings)
    return completed.returncode


def _bench_name_from_pilot_argv(argv: Sequence[str]) -> str | None:
    args = list(argv)
    for flag in ("-b", "--bench"):
        if flag in args:
            idx = args.index(flag)
            if idx + 1 < len(args):
                return args[idx + 1]
    return None


def wrap_pilot(real: str, argv: Sequence[str]) -> int:
    """Run Pilot, then reload workers after mutating commands."""
    command = first_command(argv) or ""
    settings = settings_from_env(
        {"bench_name": _bench_name_from_pilot_argv(argv) or infer_bench_name()}
    )
    env = bench_subprocess_env(settings)
    if command in {"start", "stop"}:
        return _exec([python3(), real, *argv], env=env)
    if command in {"restart", "reload"}:
        reload_bench_workers(settings, web_only="--web" in argv)
        return 0
    completed = subprocess.run([python3(), real, *argv], env=env, check=False)
    if completed.returncode == 0 and should_reload_after(argv):
        reload_bench_workers(settings)
    return completed.returncode


def render_bench_shim(real: Path, python: str, marker: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        f"{marker}\n"
        f'REAL="{real}"\n'
        f'PY="{python}"\n'
        'if [ -n "${COHENIX_SKIP_RELOAD:-}" ] && [ "${1:-}" != "start" ] '
        '&& [ "${1:-}" != "stop" ] && [ "${1:-}" != "restart" ] '
        '&& [ "${1:-}" != "reload" ]; then\n'
        '    exec "$REAL" "$@"\n'
        "fi\n"
        'if "$PY" -c "import cohenix_dev.runtime.reload" >/dev/null 2>&1; then\n'
        '    exec "$PY" -m cohenix_dev.runtime.reload --wrap-bench --real "$REAL" -- "$@"\n'
        "fi\n"
        'exec "$REAL" "$@"\n'
    )


def render_pilot_shim(real: Path, python: str, marker: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        f"{marker}\n"
        f'REAL="{real}"\n'
        f'PY="{python}"\n'
        'if "$PY" -c "import cohenix_dev.runtime.reload" >/dev/null 2>&1; then\n'
        '    exec "$PY" -m cohenix_dev.runtime.reload --wrap-pilot --real "$REAL" -- "$@"\n'
        "fi\n"
        'exec "$REAL" "$@"\n'
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cohenix-reload", description="Reload Pilot workers.")
    parser.add_argument("--wrap-bench", action="store_true")
    parser.add_argument("--wrap-pilot", action="store_true")
    parser.add_argument("--real", default="")
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--after", nargs=argparse.REMAINDER, default=None)
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    forwarded = list(args.rest)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    if args.wrap_bench:
        if not args.real:
            cprint("--wrap-bench requires --real PATH", level=1)
            return 2
        return wrap_bench(args.real, forwarded)
    if args.wrap_pilot:
        if not args.real:
            cprint("--wrap-pilot requires --real PATH", level=1)
            return 2
        return wrap_pilot(args.real, forwarded)
    if args.after is not None:
        after = list(args.after)
        if after and after[0] == "--":
            after = after[1:]
        if should_reload_after(after):
            reload_bench_workers(settings_from_env(), web_only=args.web)
        return 0
    reload_bench_workers(settings_from_env(), web_only=args.web)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
