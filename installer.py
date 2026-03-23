#!/usr/bin/env python3
"""Provision a bench aligned with Frappe v16 (version-16 branches).

Upstream declares Python >=3.14 for frappe and erpnext on version-16; the dev
image sets pyenv global to 3.14.x. Use --py-version only to override (e.g. pin
3.14.2); do not use 3.10/3.11/3.12 for v16.
"""
import argparse
import os
import subprocess
import sys

def cprint(*args, level: int = 1):
    CRED = "\033[31m"
    CGRN = "\33[92m"
    CYLW = "\33[93m"
    reset = "\033[0m"
    message = " ".join(map(str, args))
    if level == 1:
        print(CRED, message, reset)
    if level == 2:
        print(CGRN, message, reset)
    if level == 3:
        print(CYLW, message, reset)

def set_git_auto_setup_remote():
    try:
        subprocess.check_call(["git", "config", "--global", "push.autoSetupRemote", "true"])
        cprint("Successfully set git global config auto setup remote", level=3)
    except subprocess.CalledProcessError as e:
        cprint(f"Failed to set git global config: {e}", level=1)

def run_subprocess(command, cwd=None, env=None, check=True):
    try:
        subprocess.run(command, cwd=cwd, env=env, check=check)
    except subprocess.CalledProcessError as e:
        cprint(f"Command failed: {' '.join(command)}", level=1)
        sys.exit(1)


def bench_subprocess_env():
    """Env for bench commands.

    BENCH_DISABLE_UV avoids `uv venv --seed`, which downloads pip from PyPI and
    fails when DNS/network is unavailable. Stdlib `venv` seeds pip locally.
    Override by exporting BENCH_DISABLE_UV=0 before running this script.
    """
    e = os.environ.copy()
    e.setdefault("BENCH_DISABLE_UV", "1")
    return e


def main():
    parser = get_args_parser()
    args = parser.parse_args()
    set_git_auto_setup_remote()
    init_bench_if_not_exist(args)
    create_site_in_bench(args)

def get_args_parser():
    token = os.getenv("DEVELOPER_TOKEN")
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--apps-json", type=str, default=None)
    parser.add_argument("-b", "--bench-name", type=str, default="development-bench")
    parser.add_argument("-s", "--site-name", type=str, default="development.cohenix")
    parser.add_argument("-r", "--frappe-repo", type=str, default=f"https://github.com/frappe/frappe.git")
    parser.add_argument("-t", "--frappe-branch", type=str, default="version-16")
    parser.add_argument(
        "-p",
        "--py-version",
        type=str,
        default=None,
        help="Optional pyenv version for bench init (Frappe v16 needs 3.14.x, e.g. 3.14.2; omit to use default python3)",
    )
    parser.add_argument("-n", "--node-version", type=str, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-a", "--admin-password", type=str, default="admin")
    parser.add_argument("-d", "--db-type", type=str, default="mariadb")
    parser.add_argument("--db-root-username", type=str, default="root")  # Added
    parser.add_argument("--db-root-password", type=str, default="123")   # Added
    return parser

def init_bench_if_not_exist(args):
    if os.path.exists(args.bench_name):
        cprint("Bench already exists. Only site will be created", level=3)
        return
    env = bench_subprocess_env()
    init_command = ""
    if args.node_version:
        init_command += f"nvm use {args.node_version};"
    if args.py_version:
        init_command += f"PYENV_VERSION={args.py_version} "
    init_command += "bench init --skip-redis-config-generation "
    init_command += "--verbose " if args.verbose else ""
    init_command += f"--frappe-path={args.frappe_repo} "
    init_command += f"--frappe-branch={args.frappe_branch} "
    if args.apps_json:
        init_command += f"--apps_path={args.apps_json} "
    init_command += args.bench_name

    run_subprocess(["/bin/bash", "-i", "-c", init_command], env=env, cwd=os.getcwd())

    # Basic bench config
    config_pairs = [
        ("db_type", args.db_type),
        ("redis_cache", "redis://redis-cache:6379"),
        ("redis_queue", "redis://redis-queue:6379"),
        ("redis_socketio", "redis://redis-socketio:6379"),
        ("developer_mode", "1"),
    ]
    bench_cwd = os.path.join(os.getcwd(), args.bench_name)
    for key, value in config_pairs:
        run_subprocess(
            ["bench", "set-config", "-g", key, value],
            cwd=bench_cwd,
            env=bench_subprocess_env(),
        )

def create_site_in_bench(args):
    token = os.getenv("DEVELOPER_TOKEN")
    env = bench_subprocess_env()
    bench_cwd = os.path.join(os.getcwd(), args.bench_name)
    apps_to_get = [
        ("erpnext", f"https://github.com/frappe/erpnext.git", "version-16"),
        ("hrms", f"https://github.com/frappe/hrms.git", "version-16"),
    ]

    # Fetch apps
    for app_name, app_repo, app_branch in apps_to_get:
        cprint(f"Fetching app {app_name} ...", level=2)
        run_subprocess(
            ["bench", "get-app", "--branch", app_branch, app_repo],
            cwd=bench_cwd,
            env=env,
        )

    # Create site properly
    db_host = "mariadb" if args.db_type == "mariadb" else "postgresql"
    new_site_cmd = [
        "bench", "new-site",
        f"--db-type={args.db_type}",
        f"--db-host={db_host}",
        f"--db-root-username={args.db_root_username}",
        f"--db-root-password={args.db_root_password}",
        f"--admin-password={args.admin_password}",
        "--mariadb-user-host-login-scope=%",
        "--set-default",
        args.site_name,
    ]

    cprint(f"Creating Site {args.site_name} ...", level=2)
    run_subprocess(new_site_cmd, cwd=bench_cwd, env=env)

    # Install apps
    for app_name, _, _ in apps_to_get:
        cprint(f"Installing app {app_name} ...", level=2)
        run_subprocess(
            ["bench", "--site", args.site_name, "install-app", app_name],
            cwd=bench_cwd,
            env=env,
        )

    cprint("Set site developer_mode", level=3)
    run_subprocess(
        ["bench", "--site", args.site_name, "set-config", "developer_mode", "1"],
        cwd=bench_cwd,
        env=env,
    )

if __name__ == "__main__":
    main()
