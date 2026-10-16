"""Unit tests for native WSL profile resolution and toolchain pins."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESOLVER = ROOT / "scripts" / "native-wsl" / "resolve_profile.py"
PROFILES = ROOT / "config" / "profiles.toml"
TOOLCHAIN = ROOT / "toolchain.toml"


def load_resolver():
    spec = importlib.util.spec_from_file_location("resolve_profile", RESOLVER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class NativeWslProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = load_resolver()
        with PROFILES.open("rb") as handle:
            import tomllib

            cls.doc = tomllib.load(handle)

    def test_default_hr_resolves_frappe_erpnext_hrms(self) -> None:
        apps = self.mod.resolve("hr", self.doc)
        names = [a["name"] for a in apps]
        self.assertEqual(names, ["frappe", "erpnext", "hrms"])
        for app in apps:
            self.assertTrue(app["repo"].startswith("https://"))

    def test_unknown_profile_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            self.mod.resolve("not-a-profile", self.doc)

    def test_non_https_repo_rejected(self) -> None:
        doc = {
            "profiles": {
                "frappe": {
                    "apps": [{"name": "frappe", "repo": "git@github.com:frappe/frappe.git", "branch": "version-16"}]
                }
            }
        }
        with self.assertRaises(SystemExit):
            self.mod.resolve("frappe", doc)


class NativeWslToolchainTests(unittest.TestCase):
    def test_native_wsl_pilot_pin_independent_of_docker_pin(self) -> None:
        import tomllib

        data = tomllib.loads(TOOLCHAIN.read_text(encoding="utf-8"))
        docker_pin = data["pilot"]["version"]
        native = data["pilot"]["native_wsl"]
        self.assertEqual(docker_pin, "v0.0.23-pre-alpha")
        self.assertEqual(native["version"], "v0.0.64-pre-alpha")
        self.assertEqual(len(native["sha256"]), 64)
        self.assertNotEqual(docker_pin, native["version"])


if __name__ == "__main__":
    unittest.main()
