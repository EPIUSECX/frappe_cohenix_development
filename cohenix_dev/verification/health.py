"""Live process and HTTP health checks."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from cohenix_dev.config import Settings
from cohenix_dev.runtime.pilot import bench_root, import_pilot_config
from cohenix_dev.runtime.processes import read_pid
from cohenix_dev.util import command_output, port_is_live


@dataclass
class ProcessHealth:
    web: bool = False
    socketio: bool = False
    workers: bool = False
    scheduler: bool = False
    redis: bool = False
    http_ok: bool = False
    http_detail: str = ""
    realtime_detail: str = ""


def _bench_ports(settings: Settings) -> tuple[int, int, int, int]:
    _, bench_config = import_pilot_config(settings)
    config = bench_config.read(bench_root(settings))
    return config.http_port, config.socketio_port, config.redis.cache_port, config.redis.queue_port


def _pgrep(pattern: str) -> bool:
    result = command_output("pgrep", "-f", pattern)
    return result not in ("", "unknown")


def inspect_processes(settings: Settings) -> ProcessHealth:
    health = ProcessHealth()
    try:
        http_port, socketio_port, cache_port, queue_port = _bench_ports(settings)
    except Exception:  # noqa: BLE001
        return health
    health.web = port_is_live(http_port)
    health.socketio = port_is_live(socketio_port)
    health.redis = port_is_live(cache_port) and port_is_live(queue_port)
    health.workers = _pgrep("frappe.utils.background_jobs") or _pgrep("bench_helper frappe worker")
    health.scheduler = _pgrep("frappe.utils.scheduler") or _pgrep("bench_helper frappe schedule")
    if not health.workers and read_pid(settings):
        # Pilot groups workers under the start process; treat a live PID + web as workers up.
        health.workers = health.web
        health.scheduler = health.web
    if health.web:
        health.http_ok, health.http_detail = probe_http(http_port, settings.site_name)
    if health.socketio:
        health.realtime_detail = f"listening on {socketio_port}"
    return health


def probe_http(port: int, site_name: str) -> tuple[bool, str]:
    url = f"http://127.0.0.1:{port}/api/method/frappe.ping"
    request = urllib.request.Request(url, headers={"Host": site_name})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            body = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} from {url}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
    if status >= 400:
        return False, f"HTTP {status} from {url}"
    if "pong" in body.lower() or '"message"' in body:
        return True, f"HTTP {status} pong"
    try:
        data = json.loads(body)
        if data.get("message") == "pong":
            return True, "frappe.ping -> pong"
    except json.JSONDecodeError:
        pass
    return True, f"HTTP {status}"
