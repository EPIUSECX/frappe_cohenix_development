"""Host Colima runtime selection for macOS, Linux, and WSL."""

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "colima-runtime.sh"


def run_bash(script: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.pop("GITHUB_ACTIONS", None)
    merged.pop("CODESPACES", None)
    merged.pop("COLIMA_PLATFORM_OVERRIDE", None)
    merged.pop("COLIMA_DRY_RUN", None)
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env=merged,
        capture_output=True,
        text=True,
        check=False,
    )


class ColimaRuntimeTests(unittest.TestCase):
    def test_script_is_valid_bash(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_devcontainer_starts_colima_on_the_host(self):
        text = (ROOT / ".devcontainer" / "devcontainer.json").read_text()
        self.assertIn('"initializeCommand": "bash scripts/colima-runtime.sh up"', text)

    def test_installer_does_not_install_docker_engine(self):
        text = SCRIPT.read_text()
        self.assertIn("docker-ce-cli", text)
        self.assertNotIn("apt-get install -y docker-ce", text)
        self.assertIn("Colima runs dockerd", text)

    def test_platform_on_this_linux_host(self):
        result = run_bash(
            f"""
            source "{SCRIPT}"
            colima_runtime_platform
            """
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(result.stdout.strip(), {"linux", "wsl"})

    def test_mounts_home_when_repo_is_inside_home(self):
        result = run_bash(
            f"""
            source "{SCRIPT}"
            colima_runtime_mount_lines /home/ubuntu /home/ubuntu/src/frappe
            """
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["/home/ubuntu:w"])

    def test_mounts_repo_outside_home(self):
        result = run_bash(
            f"""
            source "{SCRIPT}"
            colima_runtime_mount_lines /home/ubuntu /workspace
            """
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["/home/ubuntu:w", "/workspace:w"])

    def test_release_arch_names(self):
        result = run_bash(
            f"""
            source "{SCRIPT}"
            uname() {{ printf '%s\n' "$FAKE_UNAME"; }}
            colima_runtime_release_arch macos
            colima_runtime_release_arch linux
            """,
            env={"FAKE_UNAME": "arm64"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["arm64", "aarch64"])

    def test_windows_host_is_rejected(self):
        result = run_bash(
            f'bash "{SCRIPT}" up',
            env={"COLIMA_PLATFORM_OVERRIDE": "windows", "COLIMA_DRY_RUN": "1"},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("WSL2", result.stderr)

    def test_ci_skips_colima(self):
        result = run_bash(f'bash "{SCRIPT}" up', env={"GITHUB_ACTIONS": "true"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Skipping Colima", result.stdout)
        self.assertNotIn("colima start", result.stdout)

    def test_codespaces_skips_colima(self):
        result = run_bash(f'bash "{SCRIPT}" up', env={"CODESPACES": "true"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Codespaces", result.stdout)

    def test_dry_run_prints_start_for_linux_and_macos(self):
        for platform in ("linux", "wsl", "macos"):
            with self.subTest(platform=platform):
                result = run_bash(
                    f'bash "{SCRIPT}" up',
                    env={"COLIMA_PLATFORM_OVERRIDE": platform, "COLIMA_DRY_RUN": "1", "COLIMA_MEMORY": "4"},
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("colima start", result.stdout)
                self.assertIn("--runtime docker", result.stdout)
                self.assertIn("--memory 4", result.stdout)
                self.assertNotIn("--vm-type", result.stdout)


if __name__ == "__main__":
    unittest.main()
