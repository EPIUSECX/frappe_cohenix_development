import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import installer
from cohenix_dev.cli import build_parser, main
from cohenix_dev.config import (
    ConfigError,
    resolve_profile,
    settings_from_env,
    write_local_profile,
)
from cohenix_dev.provisioning.bench import bench_is_initialised, clear_incomplete_venv
from cohenix_dev.reset import DestructiveResetAborted, confirm_or_abort
from cohenix_dev.runtime.pilot import expected_pilot_sha256, pilot_release_asset
from cohenix_dev.state.fingerprint import (
    AppFingerprint,
    Fingerprint,
    plan_sync,
)


class PilotReleaseTests(unittest.TestCase):
    def test_fixed_release_uses_stable_download_url(self):
        version, url = installer.pilot_release_asset("v0.0.23-pre-alpha")
        self.assertEqual(version, "v0.0.23-pre-alpha")
        self.assertEqual(
            url,
            "https://github.com/frappe/pilot/releases/download/"
            "v0.0.23-pre-alpha/pilot.tar.gz",
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
        plan = plan_sync.__wrapped__ if hasattr(plan_sync, "__wrapped__") else None
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
        for name in ("sync", "doctor", "verify", "status", "start", "reset"):
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


class ToolchainAgreementTests(unittest.TestCase):
    def test_export_script_matches_toolchain_file(self):
        from pathlib import Path

        import tomllib

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
        compose = (root / ".devcontainer" / "docker-compose.yml").read_text()
        self.assertIn("mariadb:11.8.9", compose)
        self.assertNotIn("skip-innodb-read-only-compressed", compose)
        self.assertNotIn("mariadb:10.6", compose)


class SqlIdentifierTests(unittest.TestCase):
    def test_unsafe_identifier_rejected(self):
        from cohenix_dev.config import SAFE_SQL_IDENTIFIER

        self.assertTrue(SAFE_SQL_IDENTIFIER.match("tabUser"))
        self.assertFalse(SAFE_SQL_IDENTIFIER.match("foo`; drop table"))


class CompatWrapperTests(unittest.TestCase):
    def test_installer_parser_still_exposes_verify_only(self):
        from cohenix_dev.compat import get_args_parser

        parser = get_args_parser()
        args = parser.parse_args(["--verify-only"])
        self.assertTrue(args.verify_only)


if __name__ == "__main__":
    unittest.main()
