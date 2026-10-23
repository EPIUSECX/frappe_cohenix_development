import unittest
from pathlib import Path
from unittest import mock

from cohenix_dev.config import Settings
from cohenix_dev.provisioning import bench


class InitBenchTests(unittest.TestCase):
    def test_new_bench_never_prompts_for_admin_password(self):
        settings = Settings(workspace="/nonexistent")
        with (
            mock.patch.object(bench, "clear_incomplete_venv"),
            mock.patch.object(bench, "bench_is_initialised", return_value=False),
            mock.patch.object(bench, "bench_root", return_value=Path("/nonexistent/bench")),
            mock.patch.object(bench, "configure_bench"),
            mock.patch.object(bench, "set_common_site_config"),
            mock.patch.object(bench, "link_bench_into_workspace"),
            mock.patch.object(bench, "run_pilot") as run_pilot,
            mock.patch("cohenix_dev.runtime.processes.ensure_bench_config_files"),
        ):
            self.assertTrue(bench.init_bench_if_not_exist(settings))
        new_call = run_pilot.call_args_list[0].args
        self.assertEqual(new_call[1], "new")
        self.assertIn("--admin-password", new_call)
        password = new_call[new_call.index("--admin-password") + 1]
        self.assertEqual(password, bench.BOOTSTRAP_ADMIN_PASSWORD)
        self.assertGreaterEqual(len(password), 8)
        self.assertNotEqual(password, password.lower())
        self.assertTrue(any(c.isdigit() for c in password))
        self.assertTrue(any(not c.isalnum() for c in password))


if __name__ == "__main__":
    unittest.main()
