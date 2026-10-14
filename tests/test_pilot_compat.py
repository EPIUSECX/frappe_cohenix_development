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
            "worker-reload",
            "procfile-omits-scheduler",
            "migrate-needs-redis",
            "venv-python-symlink",
        }
        self.assertTrue(required.issubset(ids))
        still = [item for item in data["workarounds"] if item["still_required_on_pinned"]]
        self.assertGreaterEqual(len(still), 8)

    def test_environment_tracks_the_newest_pilot_release(self):
        toolchain = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "toolchain.toml").read_text()
        )
        self.assertEqual(toolchain["pilot"]["version"], "latest")
        self.assertNotIn("canary_version", toolchain["pilot"])
