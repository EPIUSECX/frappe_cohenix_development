import inspect
import io
import time
import unittest
from unittest import mock

from cohenix_dev.config import settings_from_env
from cohenix_dev.progress import (
    START_STAGES,
    SYNC_STAGES,
    StageReporter,
    environment_rows,
    format_duration,
)


class FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FormatDurationTests(unittest.TestCase):
    def test_sub_ten_seconds_use_one_decimal(self):
        self.assertEqual(format_duration(0), "0.0s")
        self.assertEqual(format_duration(0.4), "0.4s")
        self.assertEqual(format_duration(9.9), "9.9s")

    def test_under_a_minute_are_whole_seconds(self):
        self.assertEqual(format_duration(10), "10s")
        self.assertEqual(format_duration(56), "56s")

    def test_minutes_and_hours(self):
        self.assertEqual(format_duration(328), "5m 28s")
        self.assertEqual(format_duration(3600), "1h 0m 0s")


class StageReporterTests(unittest.TestCase):
    def _reporter(self, **kwargs) -> tuple[StageReporter, io.StringIO, FakeClock]:
        buf = io.StringIO()
        clock = FakeClock()
        reporter = StageReporter(
            "devctl sync",
            SYNC_STAGES,
            stream=buf,
            clock=clock,
            heartbeat=None,
            github=False,
            **kwargs,
        )
        return reporter, buf, clock

    def test_header_lists_the_environment(self):
        reporter, buf, _clock = self._reporter()
        reporter.header([("Profile", "hr"), ("Python", "3.14.2")])
        text = buf.getvalue()
        self.assertIn("devctl sync", text)
        self.assertIn("Profile", text)
        self.assertIn("hr", text)
        self.assertIn("no prompts", text)

    def test_numbered_stages_and_elapsed_time(self):
        reporter, buf, clock = self._reporter()
        with reporter.stage("Install Pilot and Redis") as running:
            self.assertTrue(running)
            clock.advance(2.1)
        text = buf.getvalue()
        self.assertIn("[1/10] Install Pilot and Redis", text)
        self.assertIn("done (2.1s)", text)
        self.assertEqual(reporter.records[0].status, "done")
        self.assertAlmostEqual(reporter.records[0].elapsed, 2.1)

    def test_skip_does_not_run_work_when_guarded(self):
        reporter, buf, _clock = self._reporter()
        ran = False
        with reporter.stage("Migrate sites", skip=True) as running:
            if running:
                ran = True
        self.assertFalse(ran)
        self.assertIn("skipped", buf.getvalue())
        self.assertEqual(reporter.records[0].status, "skipped")

    def test_skip_rest_keeps_named_stages(self):
        reporter, buf, clock = self._reporter()
        with reporter.stage("Install Pilot and Redis"):
            clock.advance(1)
        with reporter.stage("Compare fingerprint"):
            clock.advance(0.5)
        reporter.skip_rest("nothing to do", keep=("Verify environment",))
        with reporter.stage("Verify environment") as running:
            self.assertTrue(running)
            clock.advance(0.2)
        names = {record.name: record.status for record in reporter.records}
        self.assertEqual(names["Install Pilot and Redis"], "done")
        self.assertEqual(names["Initialize bench"], "skipped")
        self.assertEqual(names["Verify environment"], "done")
        self.assertEqual(names["Save fingerprint"], "skipped")
        self.assertIn("remaining stages skipped: nothing to do", buf.getvalue())

    def test_failure_records_elapsed_and_reraises(self):
        reporter, buf, clock = self._reporter()
        with self.assertRaises(RuntimeError):
            with reporter.stage("Initialize bench"):
                clock.advance(3)
                raise RuntimeError("pilot exploded")
        self.assertEqual(reporter.records[0].status, "failed")
        self.assertAlmostEqual(reporter.records[0].elapsed, 3)
        self.assertIn("failed (3.0s)", buf.getvalue())

    def test_github_actions_groups(self):
        buf = io.StringIO()
        reporter = StageReporter(
            "devctl sync",
            ("Initialize bench",),
            stream=buf,
            heartbeat=None,
            github=True,
        )
        with reporter.stage("Initialize bench"):
            pass
        text = buf.getvalue()
        self.assertIn("::group::[1/1] Initialize bench", text)
        self.assertIn("::endgroup::", text)

    def test_summary_lists_every_stage_and_total(self):
        reporter, buf, clock = self._reporter()
        with reporter.stage("Install Pilot and Redis"):
            clock.advance(12)
        reporter.skip_rest("stop early")
        reporter.summary()
        text = buf.getvalue()
        self.assertIn("timing", text)
        self.assertIn("Install Pilot and Redis", text)
        self.assertIn("total", text)
        self.assertIn("12s", text)

    def test_heartbeat_emits_while_a_stage_is_running(self):
        buf = io.StringIO()
        reporter = StageReporter(
            "devctl sync",
            ("Initialize bench",),
            stream=buf,
            heartbeat=0.05,
            github=False,
        )
        with reporter.stage("Initialize bench"):
            time.sleep(0.18)
        self.assertIn("still [1/1] Initialize bench", buf.getvalue())


class EnvironmentRowTests(unittest.TestCase):
    def test_rows_include_profile_sites_and_apps(self):
        settings = settings_from_env({"profile": "frappe", "site_name": "cohenix.localhost"})
        rows = dict(environment_rows(settings))
        self.assertEqual(rows["Profile"], "frappe")
        self.assertIn("cohenix.localhost", rows["Sites"])
        self.assertIn("frappe", rows["Apps"])
        self.assertIn("Pilot", rows)


class WiringTests(unittest.TestCase):
    def test_sync_wraps_every_declared_stage(self):
        from cohenix_dev.provisioning import sync

        source = inspect.getsource(sync._sync_environment)
        for name in SYNC_STAGES:
            self.assertIn(name, source)

    def test_start_wraps_every_declared_stage(self):
        from cohenix_dev.runtime import processes

        source = inspect.getsource(processes._start_bench)
        for name in START_STAGES:
            self.assertIn(name, source)

    def test_sync_does_not_prompt(self):
        from cohenix_dev.provisioning import sync

        source = inspect.getsource(sync.sync_environment) + inspect.getsource(sync._sync_environment)
        self.assertNotIn("input(", source)

    def test_noop_sync_still_constructs_a_reporter(self):
        from cohenix_dev.provisioning import sync

        settings = settings_from_env({"profile": "frappe", "yes": True})
        reporter = mock.MagicMock()
        reporter.stage.return_value.__enter__.return_value = True
        reporter.stage.return_value.__exit__.return_value = False
        with (
            mock.patch.object(sync, "StageReporter", return_value=reporter),
            mock.patch.object(sync, "environment_rows", return_value=[("Profile", "frappe")]),
            mock.patch.object(sync, "set_git_auto_setup_remote"),
            mock.patch.object(sync, "ensure_pilot"),
            mock.patch.object(sync, "ensure_redis_server"),
            mock.patch.object(sync, "load_fingerprint", return_value=object()),
            mock.patch.object(sync, "desired_fingerprint", return_value=object()),
            mock.patch.object(sync, "plan_sync") as plan_sync,
            mock.patch.object(sync, "verify_installation"),
        ):
            plan = mock.Mock()
            plan.is_noop.return_value = True
            plan.describe.return_value = ["Requested configuration matches the provisioned environment"]
            plan_sync.return_value = plan
            sync.sync_environment(settings, verify=True)
        reporter.header.assert_called_once()
        reporter.skip_rest.assert_called_once()
        reporter.summary.assert_called()


if __name__ == "__main__":
    unittest.main()
