import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import installer


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


if __name__ == "__main__":
    unittest.main()
