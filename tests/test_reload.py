import os
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cohenix_dev.config import BENCH_SHIM_MARKER, PILOT_SHIM_MARKER
from cohenix_dev.runtime.reload import (
    RELOAD_REQUEST_NAME,
    SCOPE_WEB,
    SCOPE_WORKLOAD,
    SKIP_RELOAD_ENV,
    first_command,
    mutating_command,
    reload_bench_workers,
    render_bench_shim,
    render_pilot_shim,
    should_reload_after,
    supervisor_is_running,
    wait_for_reload,
    wrap_bench,
    wrap_pilot,
    write_reload_request,
)


def _settings(pilot_dir: str, bench_name: str = "development-bench") -> SimpleNamespace:
    return SimpleNamespace(
        bench_name=bench_name,
        site_name="cohenix.localhost",
        http_port=8000,
        pilot_dir=pilot_dir,
        node_version=None,
        verbose=False,
    )


class ArgvParsingTests(unittest.TestCase):
    def test_site_flag_does_not_hide_install_app(self):
        argv = ["--site", "cohenix.localhost", "install-app", "hrms"]
        self.assertEqual(first_command(argv), "install-app")
        self.assertEqual(mutating_command(argv), "install-app")
        self.assertTrue(should_reload_after(argv))

    def test_equals_form_and_verbose_flags(self):
        argv = ["--verbose", "--site=second.localhost", "migrate"]
        self.assertEqual(first_command(argv), "migrate")
        self.assertTrue(should_reload_after(argv))

    def test_pilot_frappe_passthrough(self):
        argv = ["-b", "development-bench", "frappe", "--site", "cohenix.localhost", "install-app", "payments"]
        self.assertEqual(first_command(argv), "frappe")
        self.assertEqual(mutating_command(argv), "install-app")

    def test_read_only_commands_do_not_reload(self):
        for argv in (
            ["list-apps"],
            ["--site", "cohenix.localhost", "list-apps"],
            ["start"],
            ["stop"],
            ["--help"],
        ):
            self.assertFalse(should_reload_after(argv), argv)

    def test_skip_env_disables_reload_detection(self):
        argv = ["--site", "x", "install-app", "hrms"]
        with mock.patch.dict(os.environ, {SKIP_RELOAD_ENV: "1"}):
            self.assertFalse(should_reload_after(argv))


class ReloadRequestTests(unittest.TestCase):
    def test_write_workload_and_web_scopes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_reload_request(root)
            self.assertEqual(path, root / "pids" / RELOAD_REQUEST_NAME)
            self.assertEqual(path.read_text(), SCOPE_WORKLOAD)
            write_reload_request(root, web_only=True)
            self.assertEqual(path.read_text(), SCOPE_WEB)

    def test_supervisor_pid_must_be_alive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pids").mkdir()
            self.assertFalse(supervisor_is_running(root))
            (root / "pids" / "bench.pid").write_text("99999999\n")
            self.assertFalse(supervisor_is_running(root))
            (root / "pids" / "bench.pid").write_text(f"{os.getpid()}\n")
            self.assertTrue(supervisor_is_running(root))

    def test_reload_is_noop_when_pilot_is_not_running(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "benches" / "development-bench"
            root.mkdir(parents=True)
            (root / "bench.toml").write_text("name = 'development-bench'\n")
            settings = _settings(directory)
            with mock.patch("cohenix_dev.runtime.reload.bench_root", return_value=root):
                self.assertFalse(reload_bench_workers(settings))  # type: ignore[arg-type]
            self.assertFalse((root / "pids" / RELOAD_REQUEST_NAME).exists())

    def test_reload_writes_request_when_supervisor_is_alive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "benches" / "development-bench"
            (root / "pids").mkdir(parents=True)
            (root / "bench.toml").write_text("name = 'development-bench'\n")
            (root / "pids" / "bench.pid").write_text(f"{os.getpid()}\n")
            settings = _settings(directory)
            with (
                mock.patch("cohenix_dev.runtime.reload.bench_root", return_value=root),
                mock.patch("cohenix_dev.runtime.reload.wait_for_reload", return_value=True) as wait,
            ):
                self.assertTrue(reload_bench_workers(settings))  # type: ignore[arg-type]
            self.assertEqual((root / "pids" / RELOAD_REQUEST_NAME).read_text(), SCOPE_WORKLOAD)
            wait.assert_called()

    def test_reload_waits_until_a_fake_supervisor_consumes_the_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "benches" / "development-bench"
            (root / "pids").mkdir(parents=True)
            (root / "bench.toml").write_text("name = 'development-bench'\n")
            (root / "pids" / "bench.pid").write_text(f"{os.getpid()}\n")
            consumed = threading.Event()

            def supervisor() -> None:
                path = root / "pids" / RELOAD_REQUEST_NAME
                for _ in range(80):
                    if path.is_file():
                        self.assertEqual(path.read_text(), SCOPE_WORKLOAD)
                        path.unlink()
                        consumed.set()
                        return
                    time.sleep(0.05)

            thread = threading.Thread(target=supervisor)
            thread.start()
            settings = _settings(directory)
            with (
                mock.patch("cohenix_dev.runtime.reload.bench_root", return_value=root),
                mock.patch("cohenix_dev.runtime.reload.port_is_live", return_value=True),
                mock.patch("cohenix_dev.runtime.reload._http_ok", return_value=True),
            ):
                self.assertTrue(reload_bench_workers(settings, timeout=5))  # type: ignore[arg-type]
            thread.join(timeout=5)
            self.assertTrue(consumed.is_set())
            self.assertFalse((root / "pids" / RELOAD_REQUEST_NAME).exists())

    def test_wait_returns_once_request_is_consumed_and_http_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_reload_request(root)
            settings = _settings(directory)
            path.unlink()
            with (
                mock.patch("cohenix_dev.runtime.reload.port_is_live", return_value=True),
                mock.patch("cohenix_dev.runtime.reload._http_ok", return_value=True),
            ):
                self.assertTrue(wait_for_reload(settings, root, timeout=1, http_timeout=1))  # type: ignore[arg-type]


class ShimRenderTests(unittest.TestCase):
    def test_bench_shim_is_valid_shell_and_wraps_install(self):
        text = render_bench_shim(Path("/venv/bin/bench.frappe"), "/usr/bin/python3", BENCH_SHIM_MARKER)
        self.assertIn(BENCH_SHIM_MARKER, text)
        self.assertIn("--wrap-bench", text)
        self.assertIn("COHENIX_SKIP_RELOAD", text)
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as handle:
            handle.write(text)
            path = handle.name
        try:
            result = subprocess.run(["sh", "-n", path], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            os.unlink(path)

    def test_pilot_shim_wraps_real_binary(self):
        text = render_pilot_shim(Path("/home/frappe/pilot/bin/pilot"), "/usr/bin/python3", PILOT_SHIM_MARKER)
        self.assertIn(PILOT_SHIM_MARKER, text)
        self.assertIn("--wrap-pilot", text)
        self.assertIn("/home/frappe/pilot/bin/pilot", text)

    def test_generated_shim_runs_classic_bench_for_readonly_commands(self):
        import sys

        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "bench.frappe"
            real.write_text("#!/bin/sh\necho CLASSIC\n")
            real.chmod(0o755)
            wrapper = Path(directory) / "bench"
            wrapper.write_text(render_bench_shim(real, sys.executable, BENCH_SHIM_MARKER))
            wrapper.chmod(0o755)
            env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
            result = subprocess.run(
                [str(wrapper), "list-apps"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("CLASSIC", result.stdout)

    def test_ensure_upgrades_v1_shim(self):
        from cohenix_dev.runtime.pilot import ensure_bench_start_shim

        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            (bin_dir / "bench.frappe").write_text("#!/bin/sh\necho classic\n")
            (bin_dir / "bench.frappe").chmod(0o755)
            (bin_dir / "bench").write_text(
                "#!/usr/bin/env bash\n# pilot-bench-shim v1\nexec bench.frappe \"$@\"\n"
            )
            (bin_dir / "bench").chmod(0o755)
            with mock.patch.dict(os.environ, {"VIRTUAL_ENV": directory}):
                ensure_bench_start_shim()
            text = (bin_dir / "bench").read_text()
            self.assertIn(BENCH_SHIM_MARKER, text)
            self.assertIn("--wrap-bench", text)
            self.assertNotIn("# pilot-bench-shim v1\n", text)


class WrapCommandTests(unittest.TestCase):
    def _fake_real(self, directory: str, output: str = "RAN") -> Path:
        path = Path(directory) / "real"
        path.write_text(f"#!/bin/sh\necho {output}\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return path

    def test_wrap_bench_reloads_after_successful_install_app(self):
        with tempfile.TemporaryDirectory() as directory:
            real = self._fake_real(directory)
            with (
                mock.patch("cohenix_dev.runtime.reload.settings_from_env") as settings,
                mock.patch("cohenix_dev.runtime.reload.bench_subprocess_env", return_value=os.environ.copy()),
                mock.patch("cohenix_dev.runtime.reload.reload_bench_workers") as reload,
            ):
                settings.return_value = _settings(directory)
                rc = wrap_bench(str(real), ["--site", "cohenix.localhost", "install-app", "hrms"])
            self.assertEqual(rc, 0)
            reload.assert_called_once()

    def test_wrap_bench_does_not_reload_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "real"
            real.write_text("#!/bin/sh\nexit 7\n")
            real.chmod(0o755)
            with (
                mock.patch("cohenix_dev.runtime.reload.settings_from_env") as settings,
                mock.patch("cohenix_dev.runtime.reload.bench_subprocess_env", return_value=os.environ.copy()),
                mock.patch("cohenix_dev.runtime.reload.reload_bench_workers") as reload,
            ):
                settings.return_value = _settings(directory)
                rc = wrap_bench(str(real), ["--site", "x", "install-app", "hrms"])
            self.assertEqual(rc, 7)
            reload.assert_not_called()

    def test_wrap_bench_restart_is_reload_not_full_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            real = self._fake_real(directory)
            with (
                mock.patch("cohenix_dev.runtime.reload.settings_from_env") as settings,
                mock.patch("cohenix_dev.runtime.reload.bench_subprocess_env", return_value=os.environ.copy()),
                mock.patch("cohenix_dev.runtime.reload.reload_bench_workers") as reload,
            ):
                settings.return_value = _settings(directory)
                rc = wrap_bench(str(real), ["restart", "--web"])
            self.assertEqual(rc, 0)
            reload.assert_called_once()
            self.assertTrue(reload.call_args.kwargs.get("web_only"))

    def test_wrap_pilot_reloads_after_install_app(self):
        with tempfile.TemporaryDirectory() as directory:
            real = self._fake_real(directory)
            with (
                mock.patch("cohenix_dev.runtime.reload.settings_from_env") as settings,
                mock.patch("cohenix_dev.runtime.reload.bench_subprocess_env", return_value=os.environ.copy()),
                mock.patch("cohenix_dev.runtime.reload.reload_bench_workers") as reload,
                mock.patch("cohenix_dev.runtime.reload.python3", return_value="sh"),
            ):
                settings.return_value = _settings(directory)
                rc = wrap_pilot(str(real), ["--bench", "development-bench", "install-app", "site", "hrms"])
            self.assertEqual(rc, 0)
            reload.assert_called_once()

    def test_cli_exposes_reload(self):
        from cohenix_dev.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["reload", "--web"])
        self.assertEqual(args.command, "reload")
        self.assertTrue(args.web)
        self.assertIn("reload", parser.format_help())


if __name__ == "__main__":
    unittest.main()
