"""Pilot process lifecycle and temporary Redis for site provisioning."""

from __future__ import annotations

import contextlib
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

from cohenix_dev.config import Settings
from cohenix_dev.errors import CohenixError
from cohenix_dev.output import cprint
from cohenix_dev.progress import START_STAGES, StageReporter, environment_rows
from cohenix_dev.runtime.pilot import (
    bench_root,
    bench_subprocess_env,
    import_pilot_config,
    pilot_bin,
    run_pilot,
)
from cohenix_dev.util import port_is_live, python3, which

PID_DIR = Path("/tmp")


def pid_file(settings: Settings) -> Path:
    return PID_DIR / f"pilot-{settings.bench_name}.pid"


def log_file(settings: Settings) -> Path:
    return PID_DIR / f"pilot-{settings.bench_name}.log"


def scheduler_pid_file(settings: Settings) -> Path:
    return PID_DIR / f"scheduler-{settings.bench_name}.pid"


def ensure_bench_config_files(settings: Settings) -> None:
    root = bench_root(settings)
    if not all((root / "config" / name).exists() for name in ("redis_cache.conf", "redis_queue.conf")):
        cprint("Bench config/ is incomplete, regenerating ...", level=2)
        run_pilot(settings, "--bench", settings.bench_name, "setup", "config", reload_after=False)
    ensure_scheduler_procfile(settings)


def ensure_scheduler_procfile(settings: Settings) -> None:
    """Pilot's generated Procfile omits `frappe schedule`. Add it when missing."""
    path = bench_root(settings) / "config" / "Procfile"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if any(line.startswith("schedule:") for line in text.splitlines()):
        return
    python = bench_root(settings) / "env" / "bin" / "python"
    sites = bench_root(settings) / "sites"
    line = f"schedule: bash -lc 'cd {sites} && {python} -m frappe.utils.bench_helper frappe schedule'\n"
    path.write_text(text.rstrip() + "\n" + line, encoding="utf-8")
    cprint("Added Frappe scheduler to Pilot Procfile (upstream omits it).", level=3)


def scheduler_running() -> bool:
    for pattern in ("bench_helper frappe schedule", "frappe.utils.scheduler"):
        result = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return True
    return False


def ensure_scheduler_running(settings: Settings) -> None:
    ensure_scheduler_procfile(settings)
    if scheduler_running():
        return
    root = bench_root(settings)
    python = root / "env" / "bin" / "python"
    if not python.is_file():
        return
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / "scheduler.log").open("ab") as handle:
        process = subprocess.Popen(
            [str(python), "-m", "frappe.utils.bench_helper", "frappe", "schedule"],
            cwd=str(root / "sites"),
            stdout=handle,
            stderr=handle,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=bench_subprocess_env(settings),
        )
    scheduler_pid_file(settings).write_text(f"{process.pid}\n", encoding="utf-8")
    time.sleep(0.5)
    if process.poll() is not None:
        tail = (logs / "scheduler.log").read_text(errors="ignore")[-500:]
        raise CohenixError(f"Frappe scheduler exited immediately:\n{tail}")
    cprint(f"Started Frappe scheduler as PID {process.pid} (Pilot does not start it).", level=3)


def wait_for_port(process: subprocess.Popen[bytes], port: int, label: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_is_live(port):
            return
        if process.poll() is not None:
            raise CohenixError(f"{label} exited with code {process.returncode}")
        time.sleep(0.2)
    raise CohenixError(f"Timed out waiting for {label}")


@contextlib.contextmanager
def redis_running(settings: Settings) -> Iterator[None]:
    root = bench_root(settings)
    ensure_bench_config_files(settings)
    _, bench_config = import_pilot_config(settings)
    redis = bench_config.read(root).redis
    started: list[tuple[subprocess.Popen[bytes], int, object]] = []
    try:
        for conf_name, port in (
            ("redis_cache.conf", redis.cache_port),
            ("redis_queue.conf", redis.queue_port),
        ):
            if port_is_live(port):
                cprint(f"Redis already listening on {port}, leaving it running", level=3)
                continue
            conf = root / "config" / conf_name
            if not conf.exists():
                raise CohenixError(f"Missing {conf}. Run: pilot -b {settings.bench_name} setup config")
            log = open(root / "logs" / f"{conf_name}.installer.log", "ab")  # noqa: SIM115
            binary = which("redis-server") or which("valkey-server")
            if not binary:
                raise CohenixError("redis-server is not installed")
            started.append(
                (
                    subprocess.Popen([binary, str(conf)], cwd=root, stdout=log, stderr=log),
                    port,
                    log,
                )
            )
        for process, port, _ in started:
            wait_for_port(process, port, label=f"redis on {port}")
        if started:
            cprint(f"Started Redis on {', '.join(str(p) for _, p, _ in started)} for site creation", level=3)
        yield
    finally:
        for process, _, log in started:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            log.close()
        if started:
            cprint("Stopped the temporary Redis servers", level=3)


def read_pid(settings: Settings) -> int | None:
    path = pid_file(settings)
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8").strip().splitlines()
    if not raw:
        return None
    try:
        pid = int(raw[0])
    except ValueError:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def start_bench(settings: Settings) -> None:
    reporter = StageReporter("devctl start", START_STAGES)
    reporter.header(environment_rows(settings))
    try:
        _start_bench(settings, reporter)
    except Exception:
        reporter.summary()
        raise
    reporter.summary()


def _start_bench(settings: Settings, reporter: StageReporter) -> None:
    with reporter.stage("Ensure process configuration"):
        ensure_bench_config_files(settings)
    existing = read_pid(settings)
    with reporter.stage("Start Pilot processes"):
        if existing:
            cprint(f"Pilot bench {settings.bench_name} is already running as PID {existing}.", level=2)
        else:
            binary = pilot_bin(settings)
            if not binary.exists():
                raise CohenixError(f"Pilot is not installed at {binary}; run `devctl sync` first.")
            log = log_file(settings)
            with log.open("ab") as handle:
                process = subprocess.Popen(
                    [python3(), str(binary), "-b", settings.bench_name, "start"],
                    cwd=str(binary.parent.parent),
                    stdout=handle,
                    stderr=handle,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                    env=bench_subprocess_env(settings),
                )
            pid_file(settings).write_text(f"{process.pid}\n", encoding="utf-8")
            time.sleep(2)
            if process.poll() is not None:
                tail = ""
                if log.exists():
                    tail = "\n".join(log.read_text(errors="ignore").splitlines()[-40:])
                raise CohenixError(f"Pilot failed to start. Recent output from {log}:\n{tail}")
            cprint(f"Pilot bench {settings.bench_name} started as PID {process.pid} (log: {log}).", level=2)
    with reporter.stage("Start scheduler"):
        ensure_scheduler_running(settings)


def stop_bench(settings: Settings) -> None:
    pid = read_pid(settings)
    try:
        run_pilot(settings, "-b", settings.bench_name, "stop")
    except Exception:  # noqa: BLE001
        if pid:
            try:
                os.kill(pid, 15)
            except OSError:
                pass
    scheduler = scheduler_pid_file(settings)
    if scheduler.is_file():
        try:
            os.kill(int(scheduler.read_text().strip()), 15)
        except (OSError, ValueError):
            pass
        scheduler.unlink(missing_ok=True)
    if pid_file(settings).exists():
        pid_file(settings).unlink()
    cprint(f"Pilot bench {settings.bench_name} stopped.", level=2)


def restart_bench(settings: Settings) -> None:
    stop_bench(settings)
    start_bench(settings)
