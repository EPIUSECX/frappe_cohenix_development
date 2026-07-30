#!/usr/bin/env python3
"""Provision a bench aligned with Frappe v16 (version-16 branches) using Pilot.

Pilot (https://github.com/frappe/pilot) replaces frappe/bench v5 as the bench
manager. Its CLI executable is also called `bench`, so this script installs it
under a distinct name (`pilot`) and never puts it on PATH ahead of frappe/bench.

Differences from the frappe/bench flow this replaces:

* Benches live at ``<pilot-dir>/benches/<name>`` with a declarative
  ``bench.toml``, not at ``<cwd>/<name>``. A convenience symlink is created at
  ``<cwd>/<name>`` so existing paths keep working.
* Apps are declared in ``bench.toml`` up front; ``pilot init`` clones and
  installs all of them, replacing ``bench init`` + repeated ``bench get-app``.
* Pilot runs its own Redis on localhost (it has no external-Redis option), so
  the compose redis-cache/redis-queue/redis-socketio services go unused and
  ``redis-server`` must be present in this container.
* MariaDB stays external: ``existing = true`` points Pilot at the mariadb
  service. Those credentials live in ``benches/common_config.toml``, shared by
  every bench, not in ``bench.toml``.

Upstream declares Python >=3.14 for frappe and erpnext on version-16; the dev
image sets pyenv global to 3.14.x. Use --py-version only to override (e.g. pin
3.14.2); do not use 3.10/3.11/3.12 for v16.
"""
import argparse
import contextlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

PILOT_RELEASES_URL = "https://api.github.com/repos/frappe/pilot/releases?per_page=1"

# Pilot's admin UI dependencies: the 'admin' extra from its pyproject.toml,
# minus three this container does not need and that cost a lot to resolve or
# build on Python 3.14:
#   psycopg2-binary  - Postgres only, imported lazily (no 3.14 wheel)
#   litellm          - admin LLM assistant only, very large dependency tree
#   boto3            - S3 backups only, guarded by a try/except import
ADMIN_DEPS = [
    "flask>=3.0",
    "psutil>=5.9",
    "pymysql>=1.1",
    "gunicorn>=21.2",
    "pyjwt[crypto]>=2.8",
    "PyOTP==2.10.0",
]

# Ports compose already publishes (8000-8005, 9000-9005). Pilot's own admin
# default is 7000, which compose does not forward, hence 8002 here.
DEFAULT_HTTP_PORT = 8000
DEFAULT_SOCKETIO_PORT = 9000
DEFAULT_ADMIN_PORT = 8002

SAFE_SQL_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


def cprint(*args, level: int = 1):
    CRED = "\033[31m"
    CGRN = "\33[92m"
    CYLW = "\33[93m"
    reset = "\033[0m"
    message = " ".join(map(str, args))
    # flush: subprocesses write straight to the inherited fd, so without this
    # our own lines arrive after theirs whenever stdout is a pipe (CI, logs).
    if level == 1:
        print(CRED, message, reset, flush=True)
    if level == 2:
        print(CGRN, message, reset, flush=True)
    if level == 3:
        print(CYLW, message, reset, flush=True)


def set_git_auto_setup_remote():
    try:
        subprocess.check_call(["git", "config", "--global", "push.autoSetupRemote", "true"])
        cprint("Successfully set git global config auto setup remote", level=3)
    except subprocess.CalledProcessError as e:
        cprint(f"Failed to set git global config: {e}", level=1)


def run_subprocess(command, cwd=None, env=None, check=True):
    try:
        subprocess.run(command, cwd=cwd, env=env, check=check)
    except subprocess.CalledProcessError:
        cprint(f"Command failed: {' '.join(map(str, command))}", level=1)
        sys.exit(1)


def bench_subprocess_env(args=None):
    """Env for pilot commands.

    Pilot shells out to uv, node and yarn by bare name, so ~/.local/bin (uv,
    yarn) has to be on PATH. --node-version selects an nvm-installed Node the
    way the frappe/bench flow's `nvm use` did.
    """
    e = os.environ.copy()
    path_parts = [str(Path.home() / ".local" / "bin")]
    if args is not None and args.node_version:
        nvm_dir = os.environ.get("NVM_DIR", str(Path.home() / ".nvm"))
        node_bin = Path(nvm_dir) / "versions" / "node" / f"v{args.node_version}" / "bin"
        if node_bin.is_dir():
            path_parts.insert(0, str(node_bin))
        else:
            cprint(f"Node {args.node_version} not found at {node_bin}, using PATH default", level=3)
    e["PATH"] = os.pathsep.join([*path_parts, e.get("PATH", "")])
    return e


def main():
    parser = get_args_parser()
    args = parser.parse_args()
    set_git_auto_setup_remote()
    ensure_pilot(args)
    ensure_redis_server()
    init_bench_if_not_exist(args)
    create_site_in_bench(args)


def get_args_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--apps-json", type=str, default=None)
    parser.add_argument("-b", "--bench-name", type=str, default="development-bench")
    parser.add_argument("-s", "--site-name", type=str, default="development.cohenix")
    parser.add_argument("-r", "--frappe-repo", type=str, default="https://github.com/frappe/frappe")
    parser.add_argument("-t", "--frappe-branch", type=str, default="version-16")
    parser.add_argument(
        "-p",
        "--py-version",
        type=str,
        default="3.14",
        help="Python version written to bench.toml (Frappe v16 needs 3.14.x)",
    )
    parser.add_argument("-n", "--node-version", type=str, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-a", "--admin-password", type=str, default="admin")
    parser.add_argument("-d", "--db-type", type=str, default="mariadb")
    parser.add_argument("--db-root-username", type=str, default="root")
    parser.add_argument("--db-root-password", type=str, default="123")
    parser.add_argument("--db-host", type=str, default=None, help="Defaults to the compose service name")
    parser.add_argument("--db-port", type=int, default=None, help="Defaults to 3306 / 5432")
    parser.add_argument(
        "--db-login-scope",
        type=str,
        default="%",
        help="MariaDB host scope for the site's DB user. Pilot cannot pass "
        "frappe's --mariadb-user-host-login-scope, so the grant is repaired "
        "after the site is created. Pass '' to skip.",
    )
    parser.add_argument(
        "--pilot-dir",
        type=str,
        default=os.getenv("PILOT_DIR", "/workspace/pilot"),
        help="Where Pilot is installed; benches live in <pilot-dir>/benches",
    )
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT)
    parser.add_argument("--socketio-port", type=int, default=DEFAULT_SOCKETIO_PORT)
    parser.add_argument(
        "--admin-port",
        type=int,
        default=DEFAULT_ADMIN_PORT,
        help="Pilot admin UI port (must be one compose publishes)",
    )
    parser.add_argument(
        "--admin-ui-password",
        type=str,
        default=None,
        help="Pilot admin UI password (defaults to --admin-password)",
    )
    return parser


# --------------------------------------------------------------------------
# Pilot itself
# --------------------------------------------------------------------------

def pilot_dir(args) -> Path:
    return Path(args.pilot_dir)


def benches_dir(args) -> Path:
    return pilot_dir(args) / "benches"


def bench_root(args) -> Path:
    return benches_dir(args) / args.bench_name


def ensure_pilot(args):
    """Install Pilot from its latest release tarball if it is not there yet.

    Deliberately not install.sh: that script installs MariaDB, PostgreSQL,
    nginx, supervisor and certbot system-wide and prepends its own `bench` to
    PATH, which would shadow frappe/bench 5.x in this image.
    """
    root = pilot_dir(args)
    if not (root / "bench").exists():
        cprint(f"Installing Pilot into {root} ...", level=2)
        url = latest_pilot_asset_url()
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as handle:
            tmp = Path(handle.name)
        try:
            with urllib.request.urlopen(url, timeout=120) as response, open(tmp, "wb") as out:  # noqa: S310
                shutil.copyfileobj(response, out)
            with tarfile.open(tmp) as archive:
                archive.extractall(root, filter="data")
        finally:
            tmp.unlink(missing_ok=True)
        (root / "bench").chmod(0o755)
        version = (root / "VERSION").read_text().strip() if (root / "VERSION").exists() else "unknown"
        cprint(f"Pilot {version} installed", level=2)
    else:
        cprint("Pilot already installed", level=3)

    ensure_admin_venv(args)
    ensure_pilot_on_path(args)


def latest_pilot_asset_url() -> str:
    with urllib.request.urlopen(PILOT_RELEASES_URL, timeout=60) as response:  # noqa: S310
        releases = json.load(response)
    for release in releases:
        for asset in release.get("assets", []):
            if asset.get("name") == "pilot.tar.gz":
                return asset["browser_download_url"]
    cprint("No pilot.tar.gz release asset found", level=1)
    sys.exit(1)


def ensure_admin_venv(args):
    """Pilot's admin UI runs from its own venv, separate from the bench env."""
    venv = pilot_dir(args) / ".admin-venv"
    if (venv / "bin" / "flask").exists():
        return
    env = bench_subprocess_env(args)
    cprint("Creating Pilot admin environment ...", level=2)
    run_subprocess(["uv", "venv", str(venv), "--quiet"], env=env)
    run_subprocess(
        ["uv", "pip", "install", "--python", str(venv / "bin" / "python"), *ADMIN_DEPS],
        env=env,
    )


def ensure_pilot_on_path(args):
    """Expose Pilot as `pilot`. Its own binary is named `bench`; symlinking it
    under that name would shadow frappe/bench 5.x, which this image still ships.
    """
    link = Path.home() / ".local" / "bin" / "pilot"
    link.parent.mkdir(parents=True, exist_ok=True)
    target = pilot_dir(args) / "bench"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(target)
    cprint(f"Pilot available as `pilot` ({link} -> {target})", level=3)


def run_pilot(args, *cli_args, cwd=None):
    command = [str(pilot_dir(args) / "bench")]
    if args.verbose:
        command.append("--verbose")
    command += [str(a) for a in cli_args]
    run_subprocess(command, cwd=cwd or str(pilot_dir(args)), env=bench_subprocess_env(args))


def ensure_redis_server():
    """Pilot runs its own Redis processes; it has no external-Redis setting.

    The devcontainer image ships redis-tools but not redis-server, so the
    compose redis-* services cannot be reused here.
    """
    if shutil.which("redis-server") or shutil.which("valkey-server"):
        return
    cprint("Installing redis-server (Pilot manages its own Redis) ...", level=2)
    apt_env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    run_subprocess(["sudo", "-n", "apt-get", "update"], env=apt_env)
    run_subprocess(
        ["sudo", "-n", "apt-get", "install", "-y", "--no-install-recommends", "redis-server"],
        env=apt_env,
    )
    # The distro package auto-starts a server on 6379; Pilot runs its own on
    # its configured ports, so free the port and the memory.
    subprocess.run(["sudo", "-n", "service", "redis-server", "stop"], check=False)


# --------------------------------------------------------------------------
# Bench
# --------------------------------------------------------------------------

def init_bench_if_not_exist(args):
    if (bench_root(args) / "bench.toml").exists():
        cprint("Bench already exists. Only site will be created", level=3)
        return

    cprint(f"Creating bench {args.bench_name} ...", level=2)
    run_pilot(args, "new", args.bench_name, "--database", args.db_type)
    configure_bench(args)

    cprint("Initialising bench (clone + install apps, this takes a while) ...", level=2)
    run_pilot(args, "--bench", args.bench_name, "init")

    set_common_site_config(args, {"developer_mode": 1})
    link_bench_into_workspace(args)


def apps_for_bench(args) -> list:
    """[(name, repo, branch)] for bench.toml, framework app first.

    --apps-json takes the frappe_docker apps.json shape: a list of
    {"url": ..., "branch": ...}. Without it, the default v16 set is used.
    """
    apps = [("frappe", args.frappe_repo, args.frappe_branch)]
    if args.apps_json:
        for entry in json.loads(Path(args.apps_json).read_text()):
            url = entry["url"]
            name = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
            if name == "frappe":
                continue
            apps.append((name, url, entry.get("branch") or args.frappe_branch))
        return apps

    apps += [
        ("erpnext", "https://github.com/frappe/erpnext", "version-16"),
        ("hrms", "https://github.com/frappe/hrms", "version-16"),
    ]
    return apps


def import_pilot_config(args):
    """Pilot ships no installable package; its own `bench` script imports it by
    putting the install directory on sys.path, so do the same."""
    if str(pilot_dir(args)) not in sys.path:
        sys.path.insert(0, str(pilot_dir(args)))
    from pilot.config import AppConfig, BenchConfig  # noqa: PLC0415 - needs the sys.path above

    return AppConfig, BenchConfig


def configure_bench(args):
    """Rewrite bench.toml (and the shared common_config.toml) for this container.

    Uses Pilot's own config model rather than hand-written TOML so the result
    passes its validation and stays in the shape Pilot expects.
    """
    AppConfig, BenchConfig = import_pilot_config(args)

    root = bench_root(args)
    db_host = args.db_host or ("mariadb" if args.db_type == "mariadb" else "postgresql")

    cprint("Writing bench.toml ...", level=2)
    with BenchConfig.open(root, mode="rw") as config:
        config.python_version = args.py_version
        config.apps = [
            AppConfig(name=name, repo=repo, branch=branch) for name, repo, branch in apps_for_bench(args)
        ]

        # Ports compose publishes; Pilot's defaults (admin 7000) are not forwarded.
        config.http_port = args.http_port
        config.socketio_port = args.socketio_port
        config.admin.port = args.admin_port
        config.admin.password = args.admin_ui_password or args.admin_password

        # Developer mode itself is per-site; this only allows toggling it.
        config.allow_developer_mode = True

        # The database is the compose service, not something Pilot provisions.
        # These land in benches/common_config.toml, shared by every bench.
        if args.db_type == "postgres":
            config.postgres.existing = True
            config.postgres.host = db_host
            config.postgres.port = args.db_port or 5432
            config.postgres.admin_user = args.db_root_username
            config.postgres.root_password = args.db_root_password
        else:
            config.mariadb.existing = True
            config.mariadb.host = db_host
            config.mariadb.port = args.db_port or 3306
            config.mariadb.admin_user = args.db_root_username
            config.mariadb.root_password = args.db_root_password
            # Force TCP to the mariadb service; a socket path would be probed
            # locally and there is no local server.
            config.mariadb.socket_path = ""

    for name, repo, branch in apps_for_bench(args):
        cprint(f"  app {name} <- {repo} @ {branch}", level=3)


def set_common_site_config(args, values: dict):
    """Merge keys into sites/common_site_config.json.

    Pilot rewrites this file on every `start`/`setup config`, but it merges
    rather than replaces, so extra keys survive.
    """
    path = bench_root(args) / "sites" / "common_site_config.json"
    config = json.loads(path.read_text()) if path.exists() else {}
    config.update(values)
    path.write_text(json.dumps(config, indent=1) + "\n")
    for key, value in values.items():
        cprint(f"Set common site config {key}={value}", level=3)


def link_bench_into_workspace(args):
    """Keep <cwd>/<bench-name> working; Pilot's benches live elsewhere."""
    link = Path(os.getcwd()) / args.bench_name
    if link.exists() and not link.is_symlink():
        cprint(f"{link} already exists and is not a symlink, leaving it alone", level=3)
        return
    if link.is_symlink():
        link.unlink()
    link.symlink_to(bench_root(args))
    cprint(f"Linked {link} -> {bench_root(args)}", level=3)


# --------------------------------------------------------------------------
# Site
# --------------------------------------------------------------------------

def port_is_live(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


@contextlib.contextmanager
def redis_running(args):
    """Run Pilot's two Redis servers for the duration of the block.

    frappe's new-site and install-app connect to redis_queue/redis_cache, but
    Pilot only runs Redis as processes inside `pilot start` - there is nothing
    listening on a bench that has only been initialised. Rather than start the
    whole bench, bring up just the two servers from the configs `pilot init`
    generated, then shut them down so `pilot start` can bind those ports.

    Servers already listening (e.g. the bench is running in another shell) are
    left alone.
    """
    root = bench_root(args)
    _, BenchConfig = import_pilot_config(args)
    redis = BenchConfig.read(root).redis

    started = []
    try:
        for conf_name, port in (
            ("redis_cache.conf", redis.cache_port),
            ("redis_queue.conf", redis.queue_port),
        ):
            if port_is_live(port):
                cprint(f"Redis already listening on {port}, leaving it running", level=3)
                continue
            conf = root / "config" / conf_name
            if not conf.exists():
                cprint(f"Missing {conf}. Run: pilot -b {args.bench_name} setup config", level=1)
                sys.exit(1)
            log = open(root / "logs" / f"{conf_name}.installer.log", "ab")  # noqa: SIM115 - closed below
            started.append((subprocess.Popen(["redis-server", str(conf)], cwd=root, stdout=log, stderr=log), port, log))

        for process, port, _ in started:
            wait_for_port(process, port, label=f"redis on {port}")
        if started:
            cprint(f"Started Redis on {', '.join(str(p) for _, p, _ in started)} for site creation", level=3)
        yield
    finally:
        for process, _, log in started:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            log.close()
        if started:
            cprint("Stopped the temporary Redis servers", level=3)


def wait_for_port(process, port: int, label: str, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_is_live(port):
            return
        if process.poll() is not None:
            cprint(f"{label} exited with code {process.returncode}", level=1)
            sys.exit(1)
        time.sleep(0.2)
    cprint(f"Timed out waiting for {label}", level=1)
    sys.exit(1)


def create_site_in_bench(args):
    site_path = bench_root(args) / "sites" / args.site_name
    if site_path.exists():
        cprint(f"Site {args.site_name} already exists, skipping", level=3)
        return

    app_names = [name for name, _, _ in apps_for_bench(args)]
    with redis_running(args):
        cprint(f"Creating Site {args.site_name} ...", level=2)
        run_pilot(
            args,
            "--bench",
            args.bench_name,
            "new-site",
            args.site_name,
            "--admin-password",
            args.admin_password,
            "--apps",
            *app_names,
        )

        repair_db_login_scope(args)

        # Pilot has no equivalent of frappe/bench's `new-site --set-default`,
        # so the site would only answer to its own Host header. Without this,
        # http://localhost:<http_port> returns "localhost does not exist".
        set_common_site_config(args, {"default_site": args.site_name, "serve_default_site": True})

        cprint("Set site developer_mode", level=3)
        # No `--` separator: Pilot forwards the rest verbatim to frappe's bench
        # helper, and a literal `--` there makes click read `--site` as a
        # subcommand name instead of an option.
        run_pilot(
            args,
            "--bench",
            args.bench_name,
            "frappe",
            "--site",
            args.site_name,
            "set-config",
            "developer_mode",
            "1",
        )

    cprint(f"Bench ready. Start it with: pilot -b {args.bench_name} start", level=2)
    cprint(f"  site:     http://localhost:{args.http_port}", level=2)
    cprint(f"  admin UI: http://localhost:{args.admin_port}", level=2)


def repair_db_login_scope(args):
    """Grant the site's DB user access from any host.

    frappe's new-site scopes the user to the host the root connection came from
    (``SELECT USER()``), which in compose is the frappe container's IP and
    changes when containers are recreated. frappe/bench passed
    ``--mariadb-user-host-login-scope=%``; Pilot builds the new-site command
    itself and has no way to pass it, so the grant is widened afterwards.
    """
    if not args.db_login_scope or args.db_type != "mariadb":
        return

    site_config_path = bench_root(args) / "sites" / args.site_name / "site_config.json"
    site_config = json.loads(site_config_path.read_text())
    db_name = site_config["db_name"]
    db_user = site_config.get("db_user") or db_name
    db_password = site_config["db_password"]

    for value in (db_name, db_user):
        if not SAFE_SQL_IDENTIFIER.match(value):
            cprint(f"Refusing to build SQL for unexpected identifier: {value!r}", level=1)
            sys.exit(1)

    scope = args.db_login_scope.replace("'", "''")
    password = db_password.replace("'", "''")
    statements = (
        f"CREATE USER IF NOT EXISTS '{db_user}'@'{scope}' IDENTIFIED BY '{password}';"
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'{scope}';"
        "FLUSH PRIVILEGES;"
    )

    cprint(f"Granting {db_user}@{args.db_login_scope} on {db_name} ...", level=3)
    run_subprocess(
        [
            "mariadb",
            "-h",
            args.db_host or "mariadb",
            "-P",
            str(args.db_port or 3306),
            "-u",
            args.db_root_username,
            "-e",
            statements,
        ],
        # Keeps the root password off the process list.
        env={**os.environ, "MYSQL_PWD": args.db_root_password},
    )


if __name__ == "__main__":
    main()
