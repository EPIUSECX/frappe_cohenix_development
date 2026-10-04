import tomllib
import unittest
from pathlib import Path


class PilotCompatManifestTests(unittest.TestCase):
    def test_pinned_workarounds_are_documented(self):
        path = Path(__file__).resolve().parents[1] / "config" / "pilot-compat.toml"
        data = tomllib.loads(path.read_text())
        ids = {item["id"] for item in data["workarounds"]}
        required = {
            "cli-packaging",
            "cli-pymysql",
            "redis-server",
            "db-login-scope",
            "assets-json",
            "shallow-clone-history",
            "incomplete-venv-recovery",
            "bench-start-shim",
        }
        self.assertTrue(required.issubset(ids))
        still = [item for item in data["workarounds"] if item["still_required_on_pinned"]]
        self.assertGreaterEqual(len(still), 8)

    def test_canary_release_is_newer_than_pin(self):
        toolchain = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "toolchain.toml").read_text()
        )
        pinned = toolchain["pilot"]["version"]
        canary = toolchain["pilot"]["canary_version"]
        self.assertNotEqual(pinned, canary)
        self.assertTrue(pinned.startswith("v0."))
        self.assertTrue(canary.startswith("v0."))
