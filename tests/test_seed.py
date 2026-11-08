"""Unit tests for demo HR seed helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cohenix_dev.config import Settings
from cohenix_dev.errors import CohenixError
from cohenix_dev.seed import DEFAULT_COMPANY, _seed_script, seed_hr_demo


class SeedTests(unittest.TestCase):
    def test_seed_script_mentions_company_and_employees(self):
        settings = Settings(
            bench_name="development-bench",
            site_name="cohenix.localhost",
            pilot_dir="/tmp/pilot",
            workspace="/workspace",
            profile="hr",
        )
        with mock.patch("cohenix_dev.seed.bench_root", return_value=Path("/tmp/pilot/benches/development-bench")):
            script = _seed_script(settings, company=DEFAULT_COMPANY, abbr="CD", force=False)
        self.assertIn(DEFAULT_COMPANY, script)
        self.assertIn("setup_complete", script)
        self.assertIn("HR-EMP-00001", script)
        self.assertIn("Engineering", script)

    def test_seed_requires_bench_env(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                bench_name="development-bench",
                site_name="cohenix.localhost",
                pilot_dir=directory,
                workspace="/workspace",
                profile="hr",
            )
            with self.assertRaises(CohenixError):
                seed_hr_demo(settings)


if __name__ == "__main__":
    unittest.main()
