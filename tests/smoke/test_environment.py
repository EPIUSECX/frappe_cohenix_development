"""Full environment smoke tests.

These tests require a provisioned Cohenix Dev Container. They are skipped
unless COHENIX_SMOKE=1. CI sets that variable after `devctl sync`.
"""

from __future__ import annotations

import json
import os
import socket
import time
import unittest
import urllib.request
from pathlib import Path

SMOKE = os.environ.get("COHENIX_SMOKE") == "1"


def _live(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


@unittest.skipUnless(SMOKE, "Set COHENIX_SMOKE=1 inside a provisioned development container")
class EnvironmentSmokeTests(unittest.TestCase):
    site = os.environ.get("SITE_NAME", "cohenix.localhost")
    bench = os.environ.get("BENCH_NAME", "development-bench")
    pilot_dir = Path(os.environ.get("PILOT_DIR", "/home/frappe/pilot"))

    @property
    def root(self) -> Path:
        return self.pilot_dir / "benches" / self.bench

    def test_01_runtime_binaries(self):
        import shutil

        for name in ("python3", "node", "yarn", "uv", "pilot", "bench", "redis-server", "mariadb"):
            self.assertIsNotNone(shutil.which(name), name)

    def test_02_python_and_node_generations(self):
        import subprocess
        import sys

        self.assertEqual(sys.version_info[:2], (3, 14))
        node = subprocess.check_output(["node", "--version"], text=True).strip()
        self.assertTrue(node.startswith("v24."), node)

    def test_03_bench_and_site_exist(self):
        self.assertTrue((self.root / "bench.toml").is_file())
        self.assertTrue((self.root / "apps" / "frappe").is_dir())
        self.assertTrue((self.root / "apps" / "erpnext").is_dir())
        self.assertTrue((self.root / "apps" / "hrms").is_dir())
        self.assertTrue((self.root / "sites" / self.site / "site_config.json").is_file())
        self.assertTrue((self.root / "sites" / "assets" / "assets.json").is_file())

    def test_04_installed_apps(self):
        config = json.loads((self.root / "sites" / self.site / "site_config.json").read_text())
        installed = config.get("installed_apps") or []
        for app in ("frappe", "erpnext", "hrms"):
            self.assertIn(app, installed)

    def test_05_http_ping(self):
        self.assertTrue(_live(8000), "Frappe HTTP is not listening on 8000")
        request = urllib.request.Request(
            "http://127.0.0.1:8000/api/method/frappe.ping",
            headers={"Host": self.site},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode()
            self.assertEqual(response.status, 200)
        self.assertIn("pong", body.lower())

    def test_06_socketio_port(self):
        self.assertTrue(_live(9000), "Socket.IO is not listening on 9000")

    def test_07_redis_ports(self):
        listening = [port for port in (11000, 13000) if _live(port)]
        if not listening:
            listening = [port for port in range(11000, 13010) if _live(port)]
        self.assertTrue(listening, "No Pilot Redis port is listening")

    def test_08_fingerprint_and_provenance(self):
        self.assertTrue((self.root / ".provisioning.json").is_file())
        self.assertTrue((self.root / ".cohenix" / "fingerprint.json").is_file())

    def test_09_second_site_host_routing(self):
        second = os.environ.get("SECOND_SITE", "second.localhost")
        site_dir = self.root / "sites" / second
        if not site_dir.exists():
            self.skipTest(f"{second} not created in this run")
        request = urllib.request.Request(
            "http://127.0.0.1:8000/api/method/frappe.ping",
            headers={"Host": second},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            self.assertEqual(response.status, 200)

    def test_10_bench_mutating_command_reloads_workers_without_stop(self):
        """`bench --site X …` must respawn Pilot web, not require `pilot stop`."""
        import subprocess

        web_pid_file = self.root / "pids" / "web.pid"
        supervisor = self.root / "pids" / "bench.pid"
        self.assertTrue(supervisor.is_file(), "Pilot supervisor pid is missing")
        before_supervisor = supervisor.read_text().strip()
        before_web = web_pid_file.read_text().strip() if web_pid_file.is_file() else ""
        result = subprocess.run(
            ["bench", "--site", self.site, "clear-cache"],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        deadline = time.time() + 30
        after_web = before_web
        while time.time() < deadline:
            if web_pid_file.is_file():
                after_web = web_pid_file.read_text().strip()
                if after_web and after_web != before_web:
                    break
            time.sleep(0.3)
        self.assertEqual(
            supervisor.read_text().strip(),
            before_supervisor,
            "Pilot supervisor should keep running (no full stop/start)",
        )
        self.assertNotEqual(
            after_web,
            before_web,
            "Pilot web worker should respawn after a mutating bench command",
        )
        request = urllib.request.Request(
            "http://127.0.0.1:8000/api/method/frappe.ping",
            headers={"Host": self.site},
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode()
            self.assertEqual(response.status, 200)
        self.assertIn("pong", body.lower())
