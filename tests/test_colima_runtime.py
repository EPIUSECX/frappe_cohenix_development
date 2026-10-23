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

    def test_compose_wrapper_allows_the_generated_dockerfile(self):
        result = run_bash(
            f"""
            set -euo pipefail
            tmp=$(mktemp -d)
            trap 'rm -rf "$tmp"' EXIT
            mkdir -p "$tmp/bin"
            cat > "$tmp/bin/docker-compose" <<'FAKE'
#!/bin/sh
printf 'entitlement=%s\\n' "${{BUILDX_BAKE_ENTITLEMENTS_FS-unset}}"
printf 'args=%s\\n' "$*"
FAKE
            chmod 755 "$tmp/bin/docker-compose"
            export DOCKER_CONFIG="$tmp/config"
            export COLIMA_COMPOSE_PLUGIN_OVERRIDE="$tmp/bin/docker-compose"
            source "{SCRIPT}"
            colima_runtime_install_compose_wrapper
            wrapper="$DOCKER_CONFIG/cli-plugins/docker-compose"
            test -x "$wrapper"
            test ! -L "$wrapper"
            grep -q cohenix-buildx-entitlements "$wrapper"
            "$wrapper" compose build
            BUILDX_BAKE_ENTITLEMENTS_FS=1 "$wrapper" compose build
            """
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("entitlement=0", result.stdout)
        self.assertIn("entitlement=1", result.stdout)
        self.assertEqual(result.stdout.count("args=compose build"), 2)
        self.assertIn("BUILDX_BAKE_ENTITLEMENTS_FS=0", result.stdout)

    def test_compose_wrapper_leaves_a_custom_plugin(self):
        result = run_bash(
            f"""
            set -euo pipefail
            tmp=$(mktemp -d)
            trap 'rm -rf "$tmp"' EXIT
            export DOCKER_CONFIG="$tmp/config"
            mkdir -p "$DOCKER_CONFIG/cli-plugins"
            printf 'custom-plugin\\n' > "$DOCKER_CONFIG/cli-plugins/docker-compose"
            source "{SCRIPT}"
            colima_runtime_install_compose_wrapper
            cat "$DOCKER_CONFIG/cli-plugins/docker-compose"
            """
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("custom-plugin", result.stdout)
        self.assertIn("Leaving the existing Compose plugin", result.stderr)
        self.assertNotIn("cohenix-buildx-entitlements", result.stdout)

    def test_wrapper_build_reads_a_dockerfile_outside_the_context(self):
        if subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
            self.skipTest("docker daemon is not available")
        result = run_bash(
            f"""
            set -euo pipefail
            tmp=$(mktemp -d)
            plugins="${{HOME}}/.docker/cli-plugins"
            mkdir -p "$plugins" "$tmp/ctx" "$tmp/outside"
            backup=""
            if [[ -e "$plugins/docker-compose" || -L "$plugins/docker-compose" ]]; then
                backup="$tmp/docker-compose.bak"
                mv "$plugins/docker-compose" "$backup"
            fi
            cleanup() {{
                rm -f "$plugins/docker-compose"
                if [[ -n "$backup" && -e "$backup" ]]; then
                    mv "$backup" "$plugins/docker-compose"
                fi
                docker image rm entitlement-test:local >/dev/null 2>&1 || true
                rm -rf "$tmp"
            }}
            trap cleanup EXIT
            printf 'FROM scratch\\n' > "$tmp/outside/Dockerfile"
            cat > "$tmp/ctx/compose.yml" <<'EOF'
services:
  app:
    image: entitlement-test:local
    build:
      context: .
      dockerfile: ../outside/Dockerfile
EOF
            source "{SCRIPT}"
            colima_runtime_install_compose_wrapper
            docker compose -f "$tmp/ctx/compose.yml" build
            """
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

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
