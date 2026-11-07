"""Small developer-experience helpers used by `devctl urls|logs|console|wait`."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from cohenix_dev.config import Settings
from cohenix_dev.errors import CohenixError
from cohenix_dev.output import cprint, plain
from cohenix_dev.runtime.pilot import bench_root, import_pilot_config, run_pilot
from cohenix_dev.runtime.processes import log_file, pid_file, read_pid
from cohenix_dev.util import port_is_live


def site_urls(settings: Settings) -> list[tuple[str, str]]:
    """Return (label, url) pairs for the provisioned sites and Pilot admin."""
    http_port = settings.http_port
    admin_port = settings.admin_port
    try:
        _, bench_config = import_pilot_config(settings)
        config = bench_config.read(bench_root(settings))
        http_port = int(getattr(config, "http_port", http_port) or http_port)
        admin_port = int(getattr(getattr(config, "admin", None), "port", admin_port) or admin_port)
    except Exception:  # noqa: BLE001 — Pilot may not be on PYTHONPATH yet
        pass
    rows: list[tuple[str, str]] = [
        ("default (Host routing)", f"http://localhost:{http_port}/app"),
    ]
    for site in settings.site_names():
        rows.append((site, f"http://{site}:{http_port}/app"))
    rows.append(("Pilot admin", f"http://localhost:{admin_port}"))
    if _mailpit_available():
        rows.append(("Mailpit", "http://localhost:8025"))
    return rows


def print_urls(settings: Settings) -> int:
    plain("Cohenix development URLs")
    for label, url in site_urls(settings):
        plain(f"  {label:<28} {url}")
    plain(f"  Administrator password        {settings.admin_password}")
    pid = read_pid(settings)
    if pid:
        plain(f"  Pilot PID                     {pid}")
    else:
        cprint("  Pilot is not running. Start it with `devctl start`.", level=3)
    return 0


def follow_logs(settings: Settings, *, lines: int = 80) -> int:
    path = log_file(settings)
    if not path.is_file():
        raise CohenixError(f"No Pilot log at {path}. Has `devctl start` run yet?")
    plain(f"--- {path} (last {lines} lines, then follow) ---")
    subprocess.run(["tail", "-n", str(lines), "-F", str(path)], check=False)
    return 0


def open_console(settings: Settings, site: str | None = None) -> int:
    site_name = site or settings.site_name
    root = bench_root(settings)
    if not (root / "sites" / site_name).is_dir():
        raise CohenixError(f"Site {site_name} does not exist. Run `devctl sync` or `devctl site create`.")
    run_pilot(
        settings,
        "--bench",
        settings.bench_name,
        "frappe",
        "--site",
        site_name,
        "console",
        reload_after=False,
    )
    return 0


def wait_for_ready(settings: Settings, *, timeout: float = 60.0) -> int:
    """Block until HTTP answers on the default site, or raise."""
    deadline = time.monotonic() + timeout
    host = settings.site_name
    port = settings.http_port
    last_error = "not started"
    while time.monotonic() < deadline:
        if not port_is_live(port):
            last_error = f"nothing listening on {port}"
            time.sleep(1)
            continue
        try:
            import urllib.error
            import urllib.request

            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/method/frappe.ping",
                headers={"Host": host},
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                body = response.read().decode(errors="ignore")
            if "pong" in body or response.status == 200:
                cprint(f"Ready: http://{host}:{port}/app", level=2)
                return 0
            last_error = f"unexpected response: {body[:120]}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(1)
    raise CohenixError(f"Timed out waiting for {host}:{port} ({last_error})")


def write_motd(settings: Settings) -> Path:
    """Write a short shell MOTD so new terminals show how to use the stack."""
    path = Path(os.environ.get("HOME", "/home/frappe")) / ".cohenix-motd"
    lines = [
        "Cohenix Frappe v16 ready.",
        *[f"  {label}: {url}" for label, url in site_urls(settings)[:4]],
        "  Commands: devctl doctor | urls | logs | console | sync | start",
        "  Debug: use Run and Debug → Frappe: Web (stop Pilot web first, or attach).",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def ensure_shell_motd_hook() -> None:
    """Append a one-line bashrc hook that prints the MOTD once per login shell."""
    home = Path(os.environ.get("HOME", "/home/frappe"))
    bashrc = home / ".bashrc"
    marker = "# cohenix-devctl-motd-v1"
    snippet = (
        f"{marker}\n"
        'if [ -z "${COHENIX_MOTD_SHOWN:-}" ] && [ -f "$HOME/.cohenix-motd" ]; then\n'
        '  COHENIX_MOTD_SHOWN=1 cat "$HOME/.cohenix-motd"\n'
        "fi\n"
    )
    existing = bashrc.read_text(encoding="utf-8") if bashrc.is_file() else ""
    if marker in existing:
        return
    with bashrc.open("a", encoding="utf-8") as handle:
        handle.write("\n" + snippet)


def _mailpit_available() -> bool:
    try:
        import socket

        socket.getaddrinfo("mailpit", 1025)
        return True
    except OSError:
        return False


def configure_mailpit_if_present(settings: Settings) -> bool:
    """Point the bench at Compose Mailpit when that service is on the network."""
    if not _mailpit_available():
        return False
    try:
        root = bench_root(settings)
    except Exception:  # noqa: BLE001
        return False
    if not (root / "sites").is_dir():
        return False
    from cohenix_dev.provisioning.bench import set_common_site_config

    set_common_site_config(
        settings,
        {
            "mail_server": "mailpit",
            "mail_port": 1025,
            "use_tls": 0,
            "use_ssl": 0,
            "auto_email_id": "noreply@cohenix.localhost",
        },
    )
    cprint("Mailpit detected: email routed to mailpit:1025 (UI on :8025).", level=2)
    return True
