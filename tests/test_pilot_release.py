import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cohenix_dev.config import Settings
from cohenix_dev.errors import CohenixError
from cohenix_dev.runtime.pilot import (
    PilotRelease,
    ensure_pilot,
    pilot_release_from_payload,
    replace_pilot_tree,
)


def _add(tar: tarfile.TarFile, name: str, text: str) -> None:
    raw = text.encode()
    info = tarfile.TarInfo(name)
    info.size = len(raw)
    tar.addfile(info, io.BytesIO(raw))


def _archive(directory: Path, version: str, *, evil_bench: bool = False) -> tuple[Path, str]:
    archive = directory / f"{version}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        _add(tar, "VERSION", f"{version}\n")
        _add(tar, "bin/pilot", "#!/bin/sh\necho pilot\n")
        if evil_bench:
            _add(tar, "benches/development-bench/evil.txt", "nope\n")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return archive, digest


class PilotReleasePayloadTests(unittest.TestCase):
    def test_newest_nondraft_release_supplies_the_digest(self):
        release = pilot_release_from_payload(
            [
                {
                    "tag_name": "v9.9.9",
                    "draft": True,
                    "assets": [
                        {
                            "name": "pilot.tar.gz",
                            "browser_download_url": "https://example.test/draft.tar.gz",
                            "digest": "sha256:aa",
                        }
                    ],
                },
                {
                    "tag_name": "v0.0.63-pre-alpha",
                    "draft": False,
                    "prerelease": True,
                    "assets": [
                        {"name": "other.txt", "browser_download_url": "https://example.test/other"},
                        {
                            "name": "pilot.tar.gz",
                            "browser_download_url": "https://example.test/pilot.tar.gz",
                            "digest": "sha256:abc123",
                        },
                    ],
                },
            ]
        )
        self.assertEqual(
            release,
            PilotRelease("v0.0.63-pre-alpha", "https://example.test/pilot.tar.gz", "abc123"),
        )


class PilotUpgradeTests(unittest.TestCase):
    def test_replace_keeps_benches_and_ignores_archive_benches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "benches" / "development-bench" / "marker.txt"
            marker.parent.mkdir(parents=True)
            marker.write_text("keep\n")
            (root / "VERSION").write_text("v0.0.1\n")
            (root / "archives").mkdir()
            archive, _digest = _archive(root / "archives", "v0.0.2", evil_bench=True)
            replace_pilot_tree(archive, root)
            self.assertEqual((root / "VERSION").read_text().strip(), "v0.0.2")
            self.assertEqual(marker.read_text(), "keep\n")
            self.assertFalse((root / "benches" / "development-bench" / "evil.txt").exists())
            self.assertTrue((root / "bin" / "pilot").is_file())

    def test_latest_sync_upgrades_and_checks_the_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "pilot"
            root.mkdir()
            (root / "VERSION").write_text("v0.0.1\n")
            (root / "bin").mkdir()
            (root / "bin" / "pilot").write_text("old\n")
            marker = root / "benches" / "development-bench" / "marker.txt"
            marker.parent.mkdir(parents=True)
            marker.write_text("keep\n")
            archives = Path(directory) / "archives"
            archives.mkdir()
            archive, digest = _archive(archives, "v0.0.63-pre-alpha")
            release = PilotRelease("v0.0.63-pre-alpha", "https://example.test/pilot.tar.gz", digest, "etag")
            settings = Settings(pilot_dir=str(root), pilot_version="latest", bench_name="track-bench")

            def fake_download(url: str, dest: Path) -> None:
                self.assertEqual(url, release.url)
                dest.write_bytes(archive.read_bytes())

            with (
                mock.patch("cohenix_dev.runtime.pilot.resolve_latest_pilot_release", return_value=release),
                mock.patch("cohenix_dev.runtime.pilot.download_pilot_tarball", side_effect=fake_download),
                mock.patch("cohenix_dev.runtime.pilot.ensure_pilot_cli_deps"),
                mock.patch("cohenix_dev.runtime.pilot.ensure_admin_venv"),
                mock.patch("cohenix_dev.runtime.pilot.ensure_pilot_on_path"),
                mock.patch("cohenix_dev.runtime.pilot.ensure_bench_start_shim"),
            ):
                ensure_pilot(settings)
            self.assertEqual((root / "VERSION").read_text().strip(), "v0.0.63-pre-alpha")
            self.assertEqual(marker.read_text(), "keep\n")
            cached = json.loads((root / ".cohenix-release.json").read_text())
            self.assertEqual(cached["version"], "v0.0.63-pre-alpha")
            self.assertEqual(cached["sha256"], digest)

    def test_checksum_mismatch_leaves_the_installed_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "pilot"
            (root / "bin").mkdir(parents=True)
            (root / "VERSION").write_text("v0.0.1\n")
            (root / "bin" / "pilot").write_text("old\n")
            archives = Path(directory) / "archives"
            archives.mkdir()
            archive, _digest = _archive(archives, "v0.0.2")
            release = PilotRelease("v0.0.2", "https://example.test/pilot.tar.gz", "0" * 64)
            settings = Settings(pilot_dir=str(root), pilot_version="latest", bench_name="track-bench")

            def fake_download(url: str, dest: Path) -> None:
                dest.write_bytes(archive.read_bytes())

            with (
                mock.patch("cohenix_dev.runtime.pilot.resolve_latest_pilot_release", return_value=release),
                mock.patch("cohenix_dev.runtime.pilot.download_pilot_tarball", side_effect=fake_download),
                mock.patch("cohenix_dev.runtime.pilot.ensure_pilot_cli_deps"),
                mock.patch("cohenix_dev.runtime.pilot.ensure_admin_venv"),
                mock.patch("cohenix_dev.runtime.pilot.ensure_pilot_on_path"),
                mock.patch("cohenix_dev.runtime.pilot.ensure_bench_start_shim"),
                self.assertRaises(CohenixError),
            ):
                ensure_pilot(settings)
            self.assertEqual((root / "VERSION").read_text().strip(), "v0.0.1")

    def test_release_check_failure_keeps_an_installed_pilot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "pilot"
            (root / "bin").mkdir(parents=True)
            (root / "VERSION").write_text("v0.0.63-pre-alpha\n")
            (root / "bin" / "pilot").write_text("pilot\n")
            settings = Settings(pilot_dir=str(root), pilot_version="latest", bench_name="track-bench")
            with (
                mock.patch(
                    "cohenix_dev.runtime.pilot.resolve_latest_pilot_release",
                    side_effect=CohenixError("GitHub release check failed"),
                ),
                mock.patch("cohenix_dev.runtime.pilot.download_pilot_tarball") as download,
                mock.patch("cohenix_dev.runtime.pilot.ensure_pilot_cli_deps"),
                mock.patch("cohenix_dev.runtime.pilot.ensure_admin_venv"),
                mock.patch("cohenix_dev.runtime.pilot.ensure_pilot_on_path"),
                mock.patch("cohenix_dev.runtime.pilot.ensure_bench_start_shim"),
            ):
                ensure_pilot(settings)
            download.assert_not_called()
            self.assertEqual((root / "VERSION").read_text().strip(), "v0.0.63-pre-alpha")

    def test_frozen_tag_does_not_silently_replace_another_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "pilot"
            (root / "bin").mkdir(parents=True)
            (root / "VERSION").write_text("v0.0.1\n")
            (root / "bin" / "pilot").write_text("old\n")
            settings = Settings(
                pilot_dir=str(root),
                pilot_version="v0.0.63-pre-alpha",
                bench_name="track-bench",
            )
            with self.assertRaises(CohenixError):
                ensure_pilot(settings)
            self.assertEqual((root / "VERSION").read_text().strip(), "v0.0.1")
