"""Unit tests for developer-experience helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cohenix_dev.config import Settings
from cohenix_dev.dx import (
    ensure_shell_motd_hook,
    print_urls,
    site_urls,
    wait_for_ready,
    write_motd,
)
from cohenix_dev.errors import CohenixError


class DxTests(unittest.TestCase):
    def _settings(self, pilot_dir: str) -> Settings:
        return Settings(
            bench_name="development-bench",
            site_name="cohenix.localhost",
            pilot_dir=pilot_dir,
            workspace="/workspace",
            profile="frappe",
            admin_password="admin",
            http_port=8000,
            admin_port=8002,
        )

    def test_site_urls_include_default_and_admin(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self._settings(directory)
            root = Path(directory) / "benches" / "development-bench"
            root.mkdir(parents=True)
            (root / "bench.toml").write_text(
                'name = "development-bench"\n[http]\nport = 8000\n[admin]\nport = 8002\n',
                encoding="utf-8",
            )
            fake_config = mock.Mock()
            fake_config.http_port = 8000
            fake_config.admin = mock.Mock(port=8002)

            with (
                mock.patch("cohenix_dev.dx.import_pilot_config", return_value=(None, mock.Mock(read=lambda _r: fake_config))),
                mock.patch("cohenix_dev.dx._mailpit_available", return_value=False),
            ):
                rows = site_urls(settings)
            labels = [label for label, _ in rows]
            self.assertIn("default (Host routing)", labels)
            self.assertIn("cohenix.localhost", labels)
            self.assertIn("Pilot admin", labels)

    def test_write_motd_and_bashrc_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = self._settings(str(home / "pilot"))
            with (
                mock.patch.dict("os.environ", {"HOME": str(home)}, clear=False),
                mock.patch(
                    "cohenix_dev.dx.site_urls",
                    return_value=[("site", "http://cohenix.localhost:8000/app")],
                ),
            ):
                path = write_motd(settings)
                ensure_shell_motd_hook()
            self.assertTrue(path.is_file())
            text = path.read_text(encoding="utf-8")
            self.assertIn("devctl doctor", text)
            bashrc = (home / ".bashrc").read_text(encoding="utf-8")
            self.assertIn("cohenix-devctl-motd-v1", bashrc)
            # Idempotent.
            with mock.patch.dict("os.environ", {"HOME": str(home)}, clear=False):
                ensure_shell_motd_hook()
            self.assertEqual((home / ".bashrc").read_text(encoding="utf-8").count("cohenix-devctl-motd-v1"), 1)

    def test_print_urls_mentions_stopped_pilot(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self._settings(directory)
            with (
                mock.patch(
                    "cohenix_dev.dx.site_urls",
                    return_value=[("Pilot admin", "http://localhost:8002")],
                ),
                mock.patch("cohenix_dev.dx.read_pid", return_value=None),
                mock.patch("cohenix_dev.dx.plain") as plain,
                mock.patch("cohenix_dev.dx.cprint") as cprint,
            ):
                self.assertEqual(print_urls(settings), 0)
            joined = " ".join(str(call.args[0]) for call in plain.call_args_list + cprint.call_args_list)
            self.assertIn("not running", joined)

    def test_wait_for_ready_times_out(self):
        settings = self._settings("/tmp/pilot-missing")
        with (
            mock.patch("cohenix_dev.dx.port_is_live", return_value=False),
            mock.patch("cohenix_dev.dx.time.sleep"),
            mock.patch("cohenix_dev.dx.time.monotonic", side_effect=[0, 0.5, 2.0]),
        ):
            with self.assertRaises(CohenixError):
                wait_for_ready(settings, timeout=1.0)


if __name__ == "__main__":
    unittest.main()
