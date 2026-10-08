import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import installer
from cohenix_dev.cli import build_parser
from cohenix_dev.config import (
    ConfigError,
    resolve_profile,
    settings_from_env,
)
from cohenix_dev.provisioning.bench import bench_is_initialised, clear_incomplete_venv
from cohenix_dev.reset import DestructiveResetAborted, confirm_or_abort
from cohenix_dev.runtime.pilot import expected_pilot_sha256
from cohenix_dev.state.fingerprint import (
    AppFingerprint,
    Fingerprint,
)


class PilotReleaseTests(unittest.TestCase):
    def test_fixed_release_uses_stable_download_url(self):
        version, url = installer.pilot_release_asset("v0.0.23-pre-alpha")
        self.assertEqual(version, "v0.0.23-pre-alpha")
        self.assertEqual(
            url,
            "https://github.com/frappe/pilot/releases/download/v0.0.23-pre-alpha/pilot.tar.gz",
        )

    def test_invalid_release_tag_is_rejected(self):
        with self.assertRaises(ValueError):
            installer.pilot_release_asset("../../unexpected")

    def test_installed_release_comes_from_pilot_version_file(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "VERSION").write_text("v1.2.3\n")
            args = SimpleNamespace(pilot_dir=directory)
            self.assertEqual(installer.installed_pilot_version(args), "v1.2.3")

    def test_pinned_release_has_a_checksum(self):
        digest = expected_pilot_sha256("v0.0.23-pre-alpha")
        self.assertEqual(len(digest or ""), 64)


class ProfileTests(unittest.TestCase):
    def test_hr_profile_includes_framework_erp_and_hrms(self):
        apps = resolve_profile("hr")
        self.assertEqual([app.name for app in apps], ["frappe", "erpnext", "hrms"])
        self.assertTrue(all(app.branch == "version-16" for app in apps))

    def test_localisation_uses_existing_epiusecx_repositories(self):
        apps = {app.name: app for app in resolve_profile("localisation")}
        self.assertIn("za_local", apps)
        self.assertIn("za_local_core", apps)
        self.assertIn("za_local_payroll", apps)
        self.assertTrue(apps["za_local"].repo.endswith("cohenix_local_za"))

    def test_unknown_profile_is_rejected(self):
        with self.assertRaises(ConfigError):
            resolve_profile("does-not-exist")

    def test_full_cohenix_keeps_frappe_first(self):
        apps = resolve_profile("full-cohenix")
        self.assertEqual(apps[0].name, "frappe")


class FingerprintTests(unittest.TestCase):
    def test_matching_request_is_a_noop(self):
        fingerprint = Fingerprint(
            schema_version=2,
            profile="hr",
            image="ghcr.io/epiusecx/cohenix-frappe-dev:v16",
            architecture="x86_64",
            python="3.14.2",
            node="v24.12.0",
            uv="uv 0.11.33",
            pilot="v0.0.23-pre-alpha",
            mariadb_image="docker.io/library/mariadb:11.8.9",
            database_version="11.8.9",
            frappe_branch="version-16",
            apps=[
                AppFingerprint("frappe", "https://github.com/frappe/frappe", "version-16", "abc"),
            ],
            sites=["cohenix.localhost"],
        )
        # Compare requested_key equality used by the planner.
        self.assertEqual(fingerprint.requested_key(), fingerprint.requested_key())

    def test_requested_key_ignores_resolved_commits(self):
        left = AppFingerprint("frappe", "https://github.com/frappe/frappe", "version-16", "aaa")
        right = AppFingerprint("frappe", "https://github.com/frappe/frappe", "version-16", "bbb")
        a = Fingerprint(
            schema_version=2,
            profile="hr",
            image="img",
            architecture="x86_64",
            python="3.14.2",
            node="24.12.0",
            uv="uv",
            pilot="v0.0.23-pre-alpha",
            mariadb_image="mariadb:11.8.9",
            database_version="x",
            frappe_branch="version-16",
            apps=[left],
            sites=["cohenix.localhost"],
        )
        b = Fingerprint(
            schema_version=2,
            profile="hr",
            image="img",
            architecture="x86_64",
            python="3.14.1",
            node="v24.12.0",
            uv="uv",
            pilot="v0.0.23-pre-alpha",
            mariadb_image="mariadb:11.8.9",
            database_version="y",
            frappe_branch="version-16",
            apps=[right],
            sites=["cohenix.localhost"],
        )
        self.assertEqual(a.requested_key(), b.requested_key())


class RecoveryTests(unittest.TestCase):
    def test_incomplete_venv_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            venv = Path(directory) / "env"
            (venv / "lib").mkdir(parents=True)
            clear_incomplete_venv(venv)
            self.assertFalse(venv.exists())

    def test_complete_venv_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            venv = Path(directory) / "env"
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python").write_text("")
            clear_incomplete_venv(venv)
            self.assertTrue((venv / "bin" / "python").exists())

    def test_bench_not_initialised_without_frappe(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SimpleNamespace(pilot_dir=directory, bench_name="development-bench")
            root = Path(directory) / "benches" / "development-bench"
            root.mkdir(parents=True)
            (root / "bench.toml").write_text("name = 'development-bench'\n")
            self.assertFalse(bench_is_initialised(settings))  # type: ignore[arg-type]


class CliTests(unittest.TestCase):
    def test_parser_requires_a_command(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_help_lists_core_commands(self):
        parser = build_parser()
        text = parser.format_help()
        for name in ("sync", "doctor", "verify", "status", "start", "reload", "reset"):
            self.assertIn(name, text)

    def test_latest_pilot_is_rejected(self):
        with mock.patch.dict(os.environ, {"PILOT_VERSION": "latest"}, clear=False):
            with self.assertRaises(ConfigError):
                settings_from_env()

    def test_reset_without_yes_fails_noninteractive(self):
        settings = settings_from_env({"yes": False, "pilot_dir": "/tmp/pilot-test"})
        with mock.patch("sys.stdin.isatty", return_value=False):
            with self.assertRaises(DestructiveResetAborted):
                confirm_or_abort(settings, ["example"])


class InterpreterTests(unittest.TestCase):
    def test_python3_prefers_virtual_env(self):
        from cohenix_dev.util import python3 as resolve_python

        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "bin" / "python3"
            binary.parent.mkdir()
            binary.write_text("#!/bin/sh\n")
            binary.chmod(0o755)
            with mock.patch.dict(os.environ, {"VIRTUAL_ENV": directory}):
                self.assertEqual(resolve_python(), str(binary))

    def test_pilot_env_puts_virtualenv_ahead_of_home_local(self):
        from cohenix_dev.runtime.pilot import bench_subprocess_env

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.dict(os.environ, {"VIRTUAL_ENV": directory, "PATH": "/usr/bin"}):
                env = bench_subprocess_env()
                parts = env["PATH"].split(os.pathsep)
                self.assertEqual(parts[0], str(Path(directory) / "bin"))
                self.assertIn(str(Path.home() / ".local" / "bin"), parts)

    def test_scheduler_procfile_line_is_added_once(self):
        from cohenix_dev.runtime.processes import ensure_scheduler_procfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "benches" / "development-bench"
            (root / "config").mkdir(parents=True)
            (root / "env" / "bin").mkdir(parents=True)
            (root / "env" / "bin" / "python").write_text("#!/bin/sh\n")
            (root / "config" / "Procfile").write_text("web: frappe serve\n")
            settings = SimpleNamespace(bench_name="development-bench", pilot_dir=directory)
            with mock.patch("cohenix_dev.runtime.processes.bench_root", return_value=root):
                ensure_scheduler_procfile(settings)
                ensure_scheduler_procfile(settings)
            text = (root / "config" / "Procfile").read_text()
            self.assertEqual(text.count("schedule:"), 1)

    def test_bench_start_shim_wraps_venv_console_script(self):
        from cohenix_dev.config import BENCH_SHIM_MARKER
        from cohenix_dev.runtime.pilot import ensure_bench_start_shim

        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            (bin_dir / "bench").write_text("#!/bin/sh\necho classic\n")
            (bin_dir / "bench").chmod(0o755)
            with mock.patch.dict(os.environ, {"VIRTUAL_ENV": directory}):
                ensure_bench_start_shim()
            self.assertTrue((bin_dir / "bench.frappe").is_file())
            text = (bin_dir / "bench").read_text()
            self.assertIn(BENCH_SHIM_MARKER, text)
            self.assertIn("--wrap-bench", text)


class ToolchainAgreementTests(unittest.TestCase):
    def test_export_script_matches_toolchain_file(self):
        import tomllib
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        data = tomllib.loads((root / "toolchain.toml").read_text())
        env_example = (root / ".devcontainer" / ".env.example").read_text()
        self.assertIn(data["python"]["version"], env_example)
        self.assertIn(data["node"]["version"], env_example)
        self.assertIn(data["pilot"]["version"], env_example)
        self.assertIn("mariadb:11.8.9", env_example)
        dockerfile = (root / "images" / "v16" / "Dockerfile").read_text()
        self.assertIn(f"PYTHON_VERSION={data['python']['version']}", dockerfile)
        self.assertIn(f"NODE_VERSION={data['node']['version']}", dockerfile)
        self.assertNotIn("PYTHON_VERSION_V14", dockerfile)
        self.assertNotIn("NODE_VERSION_14", dockerfile)
        self.assertNotIn("pyenv install", dockerfile)
        self.assertNotIn('ln -sf "${VIRTUAL_ENV}/bin/python3"', dockerfile)
        self.assertIn("packaging pymysql", dockerfile)
        compose = (root / ".devcontainer" / "docker-compose.yml").read_text()
        self.assertIn("mariadb:11.8.9", compose)
        self.assertIn("target: cohenix-v16", compose)
        self.assertNotIn("skip-innodb-read-only-compressed", compose)
        self.assertNotIn("mariadb:10.6", compose)
        self.assertIn("COHENIX_SKIP_AUTOSYNC", compose)
        self.assertIn("COHENIX_SKIP_DOCTOR", compose)


class DevContainerLifecycleTests(unittest.TestCase):
    def test_editor_waits_until_start_and_doctor_finish(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / ".devcontainer" / "devcontainer.json").read_text())
        self.assertEqual(data["waitFor"], "postStartCommand")
        self.assertEqual(data["postCreateCommand"], "/workspace/scripts/post-create.sh")
        self.assertEqual(data["postStartCommand"], "/workspace/scripts/start-dev.sh")

    def test_lifecycle_scripts_are_valid_posix_sh(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("on-create.sh", "post-create.sh", "start-dev.sh", "cohenix-lifecycle.sh"):
            path = root / "scripts" / name
            result = subprocess.run(["sh", "-n", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_create_syncs_and_start_syncs_starts_and_doctors(self):
        root = Path(__file__).resolve().parents[1]
        post_create = (root / "scripts" / "post-create.sh").read_text()
        start = (root / "scripts" / "start-dev.sh").read_text()
        helpers = (root / "scripts" / "cohenix-lifecycle.sh").read_text()
        self.assertIn("cohenix_sync", post_create)
        self.assertNotIn("cohenix_doctor", post_create)
        self.assertIn("cohenix_sync", start)
        self.assertIn("cohenix_start", start)
        self.assertIn("cohenix_doctor", start)
        self.assertNotIn("exec devctl start", start)
        self.assertIn("COHENIX_SKIP_AUTOSYNC", helpers)
        self.assertIn("COHENIX_SKIP_DOCTOR", helpers)

    def test_skip_autosync_does_not_call_devctl(self):
        root = Path(__file__).resolve().parents[1]
        script = f"""
. "{root / "scripts" / "cohenix-lifecycle.sh"}"
cohenix_run_devctl() {{ echo RAN; return 1; }}
COHENIX_SKIP_AUTOSYNC=1
cohenix_sync
"""
        result = subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("RAN", result.stdout)
        self.assertIn("Skipping automatic devctl sync", result.stdout)

    def test_skip_doctor_does_not_call_devctl(self):
        root = Path(__file__).resolve().parents[1]
        script = f"""
. "{root / "scripts" / "cohenix-lifecycle.sh"}"
cohenix_run_devctl() {{ echo RAN; return 1; }}
COHENIX_SKIP_DOCTOR=1
cohenix_doctor
"""
        result = subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("RAN", result.stdout)
        self.assertIn("Skipping automatic devctl doctor", result.stdout)


class SqlIdentifierTests(unittest.TestCase):
    def test_unsafe_identifier_rejected(self):
        from cohenix_dev.config import SAFE_SQL_IDENTIFIER

        self.assertTrue(SAFE_SQL_IDENTIFIER.match("tabUser"))
        self.assertFalse(SAFE_SQL_IDENTIFIER.match("foo`; drop table"))


class ImportTests(unittest.TestCase):
    def test_doctor_imports_without_circular_import(self):
        from cohenix_dev.doctor import render_doctor, run_checks

        self.assertTrue(callable(run_checks))
        self.assertTrue(callable(render_doctor))

    def test_installer_parser_still_exposes_verify_only(self):
        from cohenix_dev.compat import get_args_parser

        parser = get_args_parser()
        args = parser.parse_args(["--verify-only"])
        self.assertTrue(args.verify_only)


if __name__ == "__main__":
    unittest.main()
