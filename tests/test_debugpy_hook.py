"""Unit tests for attach-style debugpy hook management."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cohenix_dev.config import Settings
from cohenix_dev.runtime.debugpy_hook import (
    HOOK_MARKER,
    debug_status,
    disable_debugpy,
    enable_debugpy,
    is_enabled,
    render_sitecustomize,
)


class DebugpyHookTests(unittest.TestCase):
    def _settings(self, root: Path) -> Settings:
        return Settings(
            bench_name="development-bench",
            site_name="cohenix.localhost",
            pilot_dir=str(root),
            workspace="/workspace",
            profile="hr",
        )

    def _bench(self, root: Path) -> Path:
        bench = root / "benches" / "development-bench"
        site = bench / "env" / "lib" / "python3.14" / "site-packages"
        site.mkdir(parents=True)
        (bench / "env" / "bin").mkdir(parents=True)
        (bench / "env" / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
        (bench / "env" / "bin" / "python").chmod(0o755)
        return bench

    def test_render_includes_marker_and_listen(self):
        text = render_sitecustomize(5678)
        self.assertIn(HOOK_MARKER, text)
        self.assertIn("debugpy.listen", text)
        self.assertIn("5678", text)

    def test_enable_writes_state_and_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bench(root)
            settings = self._settings(root)
            with (
                mock.patch("cohenix_dev.runtime.debugpy_hook.ensure_debugpy_package"),
                mock.patch("cohenix_dev.runtime.reload.reload_bench_workers") as reload_mock,
            ):
                self.assertEqual(enable_debugpy(settings, port=5679), 0)
            state = json.loads((root / "benches/development-bench/.cohenix/debugpy.json").read_text())
            self.assertTrue(state["enabled"])
            self.assertEqual(state["port"], 5679)
            hook = root / "benches/development-bench/env/lib/python3.14/site-packages/sitecustomize.py"
            self.assertIn(HOOK_MARKER, hook.read_text(encoding="utf-8"))
            self.assertTrue(is_enabled(settings))
            reload_mock.assert_called_once()

    def test_disable_clears_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._bench(root)
            settings = self._settings(root)
            with (
                mock.patch("cohenix_dev.runtime.debugpy_hook.ensure_debugpy_package"),
                mock.patch("cohenix_dev.runtime.reload.reload_bench_workers"),
            ):
                enable_debugpy(settings, reload_workers=False)
                disable_debugpy(settings, reload_workers=False)
            hook = root / "benches/development-bench/env/lib/python3.14/site-packages/sitecustomize.py"
            self.assertFalse(hook.exists())
            self.assertFalse(is_enabled(settings))
            self.assertEqual(debug_status(settings), 0)


if __name__ == "__main__":
    unittest.main()
