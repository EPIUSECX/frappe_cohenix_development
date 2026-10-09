"""Non-interactive stage progress for `devctl`.

This is the CI-safe answer to "where is it right now?": numbered banners, elapsed
time per stage, a heartbeat while a long Pilot subprocess is quiet, GitHub
Actions log groups, and a timing table at the end. There are no prompts.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TextIO

from cohenix_dev.config import Settings, toolchain_versions
from cohenix_dev.output import CBLU, CGRN, CRED, CYLW, reset

SYNC_STAGES: tuple[str, ...] = (
    "Install Pilot and Redis",
    "Compare fingerprint",
    "Initialize bench",
    "Classic Bench compatibility",
    "Deepen app history",
    "Create sites and install apps",
    "Build assets",
    "Migrate sites",
    "Verify environment",
    "Save fingerprint",
)

START_STAGES: tuple[str, ...] = (
    "Ensure process configuration",
    "Start Pilot processes",
    "Start scheduler",
)

DEFAULT_HEARTBEAT = 15.0


@dataclass(frozen=True)
class StageRecord:
    name: str
    status: str
    elapsed: float


def format_duration(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    return f"{minutes}m {secs}s"


def environment_rows(settings: Settings) -> list[tuple[str, str]]:
    versions = toolchain_versions()
    return [
        ("Profile", settings.profile),
        ("Python", settings.py_version or versions["python"]),
        ("Node", settings.node_version or versions["node"]),
        ("Pilot", settings.pilot_version),
        ("Bench", settings.bench_name),
        ("Sites", ", ".join(settings.site_names())),
        ("Apps", ", ".join(spec.name for spec in settings.apps())),
    ]


def in_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


class StageReporter:
    """Print where a long `devctl` command is, without asking the user anything."""

    def __init__(
        self,
        title: str,
        stages: Sequence[str],
        *,
        stream: TextIO | None = None,
        clock: Callable[[], float] | None = None,
        heartbeat: float | None = DEFAULT_HEARTBEAT,
        github: bool | None = None,
    ) -> None:
        self.title = title
        self.stages = list(stages)
        self.stream = stream or sys.stdout
        self._clock = clock or time.monotonic
        self.heartbeat = heartbeat if heartbeat and heartbeat > 0 else None
        self.github = in_github_actions() if github is None else github
        self._started_at = self._clock()
        self._records: list[StageRecord] = []
        self._done: set[str] = set()
        self._lock = threading.Lock()
        self._failed = False

    @property
    def records(self) -> list[StageRecord]:
        return list(self._records)

    def header(self, rows: Sequence[tuple[str, str]]) -> None:
        width = 72
        self._rule(width)
        self._print(f"  Cohenix  {self.title}", level=4)
        for key, value in rows:
            self._print(f"  {key:<10} {value}", level=4)
        self._print(f"  Stages    {len(self.stages)}  (no prompts; Ctrl-C to abort)", level=4)
        self._rule(width)

    @contextmanager
    def stage(self, name: str, *, skip: bool = False) -> Iterator[bool]:
        if name not in self.stages:
            self.stages.append(name)
        if name in self._done:
            yield False
            return
        if skip:
            self._record(name, "skipped", 0.0)
            self._emit_skip(name)
            yield False
            return
        start = self._clock()
        self._emit_start(name)
        heartbeat = self._start_heartbeat(name, start)
        try:
            yield True
        except Exception:
            elapsed = max(0.0, self._clock() - start)
            self._stop_heartbeat(heartbeat)
            self._failed = True
            self._record(name, "failed", elapsed)
            self._emit_fail(name, elapsed)
            raise
        else:
            elapsed = max(0.0, self._clock() - start)
            self._stop_heartbeat(heartbeat)
            self._record(name, "done", elapsed)
            self._emit_done(name, elapsed)

    def skip_rest(self, reason: str, *, keep: Sequence[str] = ()) -> None:
        keep_set = set(keep)
        self._print(f"  remaining stages skipped: {reason}", level=3)
        for name in list(self.stages):
            if name in self._done or name in keep_set:
                continue
            self._record(name, "skipped", 0.0)
            self._emit_skip(name)

    def summary(self) -> None:
        width = 72
        self._rule(width)
        self._print("  timing", level=4)
        for record in self._records:
            self._print(
                f"  {record.name:<36} {record.status:<8} {format_duration(record.elapsed):>10}",
                level=1 if record.status == "failed" else 2 if record.status == "done" else 3,
            )
        total = max(0.0, self._clock() - self._started_at)
        status = "failed" if self._failed else "complete"
        self._print(
            f"  {'total':<36} {status:<8} {format_duration(total):>10}",
            level=2 if not self._failed else 1,
        )
        self._rule(width)

    def _number(self, name: str) -> tuple[int, int]:
        try:
            index = self.stages.index(name) + 1
        except ValueError:
            self.stages.append(name)
            index = len(self.stages)
        return index, len(self.stages)

    def _record(self, name: str, status: str, elapsed: float) -> None:
        self._records.append(StageRecord(name, status, elapsed))
        self._done.add(name)

    def _emit_start(self, name: str) -> None:
        n, total = self._number(name)
        if self.github:
            print(f"::group::[{n}/{total}] {name}", file=self.stream, flush=True)
        self._print(f">>> [{n}/{total}] {name}", level=3)

    def _emit_done(self, name: str, elapsed: float) -> None:
        n, total = self._number(name)
        self._print(f"<<< [{n}/{total}] {name}  done ({format_duration(elapsed)})", level=2)
        if self.github:
            print("::endgroup::", file=self.stream, flush=True)

    def _emit_fail(self, name: str, elapsed: float) -> None:
        n, total = self._number(name)
        self._print(f"<<< [{n}/{total}] {name}  failed ({format_duration(elapsed)})", level=1)
        if self.github:
            print("::endgroup::", file=self.stream, flush=True)

    def _emit_skip(self, name: str) -> None:
        n, total = self._number(name)
        self._print(f"--- [{n}/{total}] {name}  skipped", level=3)

    def _start_heartbeat(self, name: str, start: float) -> tuple[threading.Event, threading.Thread] | None:
        if not self.heartbeat:
            return None
        stop = threading.Event()

        def loop() -> None:
            while not stop.wait(self.heartbeat):
                elapsed = max(0.0, self._clock() - start)
                n, total = self._number(name)
                self._print(
                    f"  ... still [{n}/{total}] {name} ({format_duration(elapsed)} elapsed)",
                    level=4,
                )

        thread = threading.Thread(target=loop, name=f"cohenix-progress-{name}", daemon=True)
        thread.start()
        return stop, thread

    def _stop_heartbeat(self, heartbeat: tuple[threading.Event, threading.Thread] | None) -> None:
        if heartbeat is None:
            return
        stop, thread = heartbeat
        stop.set()
        thread.join(timeout=1.0)

    def _rule(self, width: int) -> None:
        self._print("=" * width, level=4)

    def _print(self, message: str, *, level: int) -> None:
        color = {1: CRED, 2: CGRN, 3: CYLW}.get(level, CBLU)
        with self._lock:
            print(f"{color}{message}{reset}", file=self.stream, flush=True)
