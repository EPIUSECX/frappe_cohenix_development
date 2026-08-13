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
* Ports belong to the *bench*, not the site. Every site on a bench answers on
  the same ``http_port`` and is picked out by Host header, so extra sites need
  resolvable names rather than free ports -- hence the ``.localhost`` default
  and ``--extra-sites``. Only a new bench gets new ports, and Pilot offsets all
  of them at once (see ``bench_ports``).

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
import tomllib
import urllib.request
from pathlib import Path

PILOT_RELEASES_URL = "https://api.github.com/repos/frappe/pilot/releases?per_page=1"

# Third-party imports the *CLI* needs, which nothing else installs for it.
#
# Pilot's bin/pilot claims "All dependencies are stdlib only" and its
# pyproject declares `dependencies = []`, but the CLI import graph reaches
# `packaging` (pilot/integrations/marketplace.py and pilot/core/app/validator/*)
# and `pymysql` (pilot/core/database/engines/mariadb.py). Nothing installs
# them: install.sh only populates .admin-venv, and that is a different
# interpreter, so the admin UI works while the CLI does not.
#
# `packaging` is the fatal one. bin/pilot runs under `#!/usr/bin/env python3`,
# i.e. bare pyenv, where it is absent -- pip vendors its own copy under
# pip._vendor and never exposes the top-level name. So `pilot new-site --apps
# frappe erpnext hrms` creates the site, installs frappe (the framework app,
# which new-site handles itself), then dies with "ModuleNotFoundError: No
# module named 'packaging'" the instant SiteProvisioner.install_apps() touches
# the second app. Result: an "Active" site with frappe and nothing else.
#
# `pymysql` is not fatal -- Pilot's site DB probes catch every exception and
# report "no rows" -- but without it those probes silently answer wrong.
PILOT_CLI_DEPS = ["packaging", "pymysql"]

# Only used if a release ever ships without pyproject.toml; mirrors the same
# fallback in Pilot's own AdminEnvManager._read_admin_deps.
ADMIN_DEPS_FALLBACK = [
    "flask>=3.0",
    "psutil>=5.9",
    "pymysql>=1.1",
    "gunicorn>=21.2",
    "pyjwt[crypto]>=2.8",
]

# Ports compose already publishes (8000-8005, 9000-9005). Pilot's own admin
# default is 7000, which compose does not forward, hence 8002 here.
DEFAULT_HTTP_PORT = 8000
DEFAULT_SOCKETIO_PORT = 9000
DEFAULT_ADMIN_PORT = 8002

# Everything docker-compose.yml forwards to the host. A port outside these is
# reachable inside the container and nowhere else, which looks exactly like a
# broken bench from the browser.
PUBLISHED_PORTS = frozenset(range(8000, 8006)) | frozenset(range(9000, 9006))

# How far back to deepen Pilot's --depth 1 app clones, and the commit count
# below which a clone is still one of them. Anything deepened lands in the
# thousands, so the gap between the two is wide enough not to need tuning.
APP_HISTORY_DEPTH = 200
SHALLOW_CLONE_MAX_COMMITS = 50

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
    ensure_classic_bench_compat(args)
    ensure_app_history(args)
    create_site_in_bench(args)


def get_args_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", "--apps-json", type=str, default=None)
    parser.add_argument("-b", "--bench-name", type=str, default="development-bench")
    # A `.localhost` name resolves to loopback on macOS, Linux and Windows with
    # no /etc/hosts entry, which matters because Pilot cannot give you one:
    # SiteProvisioner.add_to_hosts writes to the *container's* /etc/hosts, where
    # no browser will ever read it. Sites on one bench share the HTTP port and
    # are told apart by Host header (frappe.utils.get_site_name splits the port
    # off and uses the rest as the directory name), so the name is the only
    # thing making a second site reachable.
    parser.add_argument("-s", "--site-name", type=str, default="cohenix.localhost")
    parser.add_argument(
        "--extra-sites",
        type=str,
        nargs="*",
        default=[],
        metavar="NAME",
        help="Further sites to create on the same bench with the same apps. They "
        "share the bench's HTTP port and are routed by Host header, so give them "
        "'.localhost' names unless you enjoy editing /etc/hosts.",
    )
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
        pilot_executable = root / "bin" / "pilot"
        bench_link = root / "bench"
        if not bench_link.exists():
            if pilot_executable.exists():
                bench_link.symlink_to(pilot_executable)
            else:
                raise FileNotFoundError(
                    f"Pilot installation missing executable: {pilot_executable}"
                )
        bench_link.chmod(0o755)
        version = (root / "VERSION").read_text().strip() if (root / "VERSION").exists() else "unknown"
        cprint(f"Pilot {version} installed", level=2)
    else:
        cprint("Pilot already installed", level=3)

    ensure_pilot_cli_deps()
    ensure_admin_venv(args)
    ensure_pilot_on_path(args)


def pilot_cli_python() -> str:
    """The interpreter Pilot's CLI actually runs under.

    bin/pilot has a `#!/usr/bin/env python3` shebang and inserts its install
    directory on sys.path, so the CLI runs on whatever `python3` resolves to --
    the pyenv global, not the bench env and not .admin-venv.
    """
    return shutil.which("python3") or sys.executable


def ensure_pilot_cli_deps():
    """Install PILOT_CLI_DEPS into the interpreter that runs `pilot`.

    Runs on every invocation, not just a fresh install: a Pilot upgrade can add
    an undeclared import, and this is cheap once the modules are there.
    """
    python = pilot_cli_python()
    probe = subprocess.run(
        [python, "-c", "import importlib.util as u,sys;"
         "print(' '.join(m for m in sys.argv[1:] if u.find_spec(m) is None))", *PILOT_CLI_DEPS],
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        cprint(f"Could not probe {python} for Pilot's CLI dependencies:\n{probe.stderr}", level=1)
        sys.exit(1)
    missing = probe.stdout.split()
    if not missing:
        return
    cprint(f"Installing Pilot CLI dependencies into {python}: {', '.join(missing)}", level=2)
    run_subprocess(
        [python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", *missing],
        env=bench_subprocess_env(),
    )


def latest_pilot_asset_url() -> str:
    with urllib.request.urlopen(PILOT_RELEASES_URL, timeout=60) as response:  # noqa: S310
        releases = json.load(response)
    for release in releases:
        for asset in release.get("assets", []):
            if asset.get("name") == "pilot.tar.gz":
                return asset["browser_download_url"]
    cprint("No pilot.tar.gz release asset found", level=1)
    sys.exit(1)


def admin_deps(args) -> list:
    """The full 'admin' extra, read from Pilot's own pyproject.toml.

    Read rather than hardcoded so the list cannot drift from the release that
    is actually installed.
    """
    pyproject = pilot_dir(args) / "pyproject.toml"
    if not pyproject.exists():
        return list(ADMIN_DEPS_FALLBACK)
    with open(pyproject, "rb") as handle:
        data = tomllib.load(handle)
    extras = data.get("project", {}).get("optional-dependencies", {})
    return extras.get("admin") or list(ADMIN_DEPS_FALLBACK)


def ensure_admin_venv(args):
    """Pilot's admin UI runs from its own venv, separate from the bench env.

    Installs the complete 'admin' extra, not a subset. `pilot init` calls
    AdminEnvManager.ensure(), which installs the full set regardless of what
    lands here and only skips when <venv>/.admin-deps already records exactly
    those deps -- so a trimmed list buys nothing but a second, slower install.
    Writing that stamp is deliberately left to Pilot, so a later Pilot upgrade
    can still add dependencies.
    """
    venv = pilot_dir(args) / ".admin-venv"
    if (venv / "bin" / "flask").exists():
        return
    deps = admin_deps(args)
    env = bench_subprocess_env(args)
    cprint("Creating Pilot admin environment ...", level=2)
    run_subprocess(["uv", "venv", str(venv), "--quiet"], env=env)
    cprint(f"Installing {len(deps)} admin dependencies (several minutes) ...", level=2)
    run_subprocess(
        ["uv", "pip", "install", "--python", str(venv / "bin" / "python"), *deps],
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


def ensure_classic_bench_compat(args):
    """Let frappe/bench 5.x commands run inside a Pilot bench.

    This image still ships frappe/bench, and it is still the natural way to run
    site-level commands (migrate, build, console, execute). Its
    is_bench_directory() requires all of ('apps', 'sites', 'config', 'logs',
    'config/pids'). Pilot creates every one of those except the last -- it keeps
    pid files in a top-level pids/ -- so without this, every classic bench
    command in the bench directory aborts with "Command not being executed in
    bench directory". Pilot neither reads nor writes config/pids.

    Note this only enables site-level commands. `bench start` still does not
    work: Pilot writes no Procfile and runs its own process set.
    """
    pids = bench_root(args) / "config" / "pids"
    if pids.is_dir():
        return
    if not (bench_root(args) / "bench.toml").exists():
        return
    pids.mkdir(parents=True, exist_ok=True)
    cprint(f"Created {pids} so frappe/bench commands work in the bench directory", level=3)


def app_commit_count(path: Path) -> int:
    """Commits reachable from HEAD, or 0 when git cannot say."""
    result = subprocess.run(
        ["git", "-C", str(path), "rev-list", "--count", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return 0
    return int(result.stdout.strip() or 0)


def ensure_app_history(args):
    """Deepen the app clones Pilot made at --depth 1.

    Pilot clones apps shallow unless it is running as a dev build
    (AppRepository.depth_flags -> is_dev_build -> VERSION == "dev"), and we
    install from the release tarball, so every app arrives with exactly one
    commit. Two consequences:

    * Pilot's own update check breaks, and breaks *dangerously*. It decides by
      git ancestry rather than version labels -- `not repo.is_ancestor(target,
      HEAD)` in AppRepository._is_ahead_of_installed -- which is the right idea,
      but with no history git cannot answer and the check fails open. Tracking a
      branch tip that runs ahead of the marketplace registry's validated pin
      (e.g. erpnext version-16 at 16.32.0 vs a registry pinned to 16.30.0) then
      shows up in the admin UI as an available update, and its one-click "Update
      all" would check out the older commit and migrate the site *backwards*.
    * `git log`, `blame` and branching are all useless on a bench whose entire
      point is development.

    A bounded deepen fixes both without paying for the full history of every
    app. Failures are warnings, not errors: this improves a working bench, it is
    not required for one.
    """
    for name, _, branch in apps_for_bench(args):
        path = bench_root(args) / "apps" / name
        if not (path / ".git").exists():
            continue
        if app_commit_count(path) >= SHALLOW_CLONE_MAX_COMMITS:
            continue
        cprint(f"Deepening {name} history to ~{APP_HISTORY_DEPTH} commits ...", level=3)
        result = subprocess.run(
            ["git", "-C", str(path), "fetch", f"--depth={APP_HISTORY_DEPTH}", "origin", branch],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            cprint(
                f"Could not deepen {name} ({result.stderr.strip()}).\n"
                f"  Pilot may offer a downgrade as an 'update' for this app -- check the "
                f"version numbers before accepting one.",
                level=3,
            )


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


def sibling_bench_ports(args) -> dict:
    """{port: bench name} for every other bench that already claims one."""
    _, BenchConfig = import_pilot_config(args)

    claimed = {}
    for toml_path in sorted(benches_dir(args).glob("*/bench.toml")):
        name = toml_path.parent.name
        if name == args.bench_name:
            continue
        try:
            config = BenchConfig.read(toml_path.parent)
        except Exception:  # noqa: BLE001 - a sibling we cannot parse just goes unchecked
            continue
        for port in (config.http_port, config.socketio_port, config.admin.port):
            claimed[port] = name
    return claimed


def bench_ports(args) -> dict:
    """The http/socketio/admin ports this bench should use.

    `pilot new` picks a port offset off the benches it can see
    (BenchCreator._pick_port_offset) and shifts every port by it. We then have
    to overwrite http/socketio/admin, because Pilot's defaults (8000/9000/7000)
    include one compose does not publish -- and overwriting them with constants
    threw that offset away, so a second bench landed straight back on 8000 and
    collided with the first. Re-apply the offset instead, and refuse to write a
    config that cannot work rather than discovering it at `pilot start`.

    Explicitly passed ports are taken verbatim: if you name a port, you mean it.
    """
    _, BenchConfig = import_pilot_config(args)

    offset = BenchConfig.current_port_offset(bench_root(args) / "bench.toml")
    defaults = {
        "http": DEFAULT_HTTP_PORT,
        "socketio": DEFAULT_SOCKETIO_PORT,
        "admin": DEFAULT_ADMIN_PORT,
    }
    chosen = {"http": args.http_port, "socketio": args.socketio_port, "admin": args.admin_port}
    ports = {
        role: value if value != defaults[role] else value + offset
        for role, value in chosen.items()
    }
    if offset:
        cprint(f"Pilot picked port offset {offset} for this bench", level=3)

    claimed = sibling_bench_ports(args)
    problems = []
    for role, port in sorted(ports.items(), key=lambda item: item[1]):
        if port not in PUBLISHED_PORTS:
            problems.append(
                f"  {role} port {port} is not published by docker-compose.yml "
                f"(it forwards 8000-8005 and 9000-9005), so nothing on your host can reach it"
            )
        elif port in claimed:
            problems.append(f"  {role} port {port} is already used by bench '{claimed[port]}'")
    if len(set(ports.values())) != len(ports):
        problems.append(f"  two roles were given the same port: {ports}")

    if problems:
        cprint(
            "Cannot allocate ports for this bench:\n"
            + "\n".join(problems)
            + "\nWiden the ports: range in .devcontainer/docker-compose.yml, or pass "
            "--http-port/--socketio-port/--admin-port explicitly.",
            level=1,
        )
        sys.exit(1)
    return ports


def configure_bench(args):
    """Rewrite bench.toml (and the shared common_config.toml) for this container.

    Uses Pilot's own config model rather than hand-written TOML so the result
    passes its validation and stays in the shape Pilot expects.
    """
    AppConfig, BenchConfig = import_pilot_config(args)

    root = bench_root(args)
    ports = bench_ports(args)
    db_host = args.db_host or ("mariadb" if args.db_type == "mariadb" else "postgresql")

    cprint("Writing bench.toml ...", level=2)
    with BenchConfig.open(root, mode="rw") as config:
        config.python_version = args.py_version
        config.apps = [
            AppConfig(name=name, repo=repo, branch=branch) for name, repo, branch in apps_for_bench(args)
        ]

        # Ports compose publishes; Pilot's defaults (admin 7000) are not
        # forwarded. Redis is left alone: it is container-local, so Pilot's own
        # offset is already right for it.
        config.http_port = ports["http"]
        config.socketio_port = ports["socketio"]
        config.admin.port = ports["admin"]
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


def all_site_names(args) -> list:
    """Every site this run should end up with, the default one first."""
    names = [args.site_name]
    names += [name for name in args.extra_sites if name not in names]
    return names


def site_installed_apps(args, site_name: str) -> list:
    """Apps recorded on the site, straight from site_config.json.

    Read here rather than via `pilot list-site-apps`, which needs the site's DB
    to be reachable and answers with an empty list when it is not -- that would
    look identical to a site with no apps and trigger a pointless reinstall.
    """
    path = bench_root(args) / "sites" / site_name / "site_config.json"
    if not path.exists():
        return []
    return json.loads(path.read_text()).get("installed_apps", [])


def provision_site(args, site_name: str, app_names: list):
    """Create the site, or finish one a previous run left half-built."""
    if (bench_root(args) / "sites" / site_name).exists():
        # A provision that dies partway leaves the site behind with only the
        # apps it got to, and Pilot's new-site refuses to touch an existing
        # site. Skipping outright would make every re-run a no-op and leave the
        # half-built site half-built forever, so finish it instead: install what
        # is missing, then carry on to the steps the failed run never reached.
        missing = [name for name in app_names if name not in site_installed_apps(args, site_name)]
        if not missing:
            cprint(f"Site {site_name} already exists with all apps, skipping creation", level=3)
        else:
            cprint(
                f"Site {site_name} exists but is missing {', '.join(missing)}; "
                f"installing (a previous run must have failed partway)",
                level=3,
            )
            run_pilot(args, "--bench", args.bench_name, "install-app", site_name, *missing)
    else:
        cprint(f"Creating Site {site_name} ...", level=2)
        run_pilot(
            args,
            "--bench",
            args.bench_name,
            "new-site",
            site_name,
            "--admin-password",
            args.admin_password,
            "--apps",
            *app_names,
        )

    repair_db_login_scope(args, site_name)

    cprint(f"Set developer_mode on {site_name}", level=3)
    # No `--` separator: Pilot forwards the rest verbatim to frappe's bench
    # helper, and a literal `--` there makes click read `--site` as a
    # subcommand name instead of an option.
    run_pilot(
        args,
        "--bench",
        args.bench_name,
        "frappe",
        "--site",
        site_name,
        "set-config",
        "developer_mode",
        "1",
    )


def ensure_assets_built(args):
    """Make sure sites/assets/assets.json exists.

    Pilot's SiteProvisioner.build_missing_assets() decides whether to build by
    asking whether ``sites/assets/<app>`` exists -- but that directory is a
    symlink to the app's public/ folder, created by the asset *linking* step
    that `pilot init` and `pilot start` run regardless of whether esbuild has
    ever produced a bundle. So on any bench where the link already exists, it
    builds nothing, and the bench-wide manifest never gets written.

    Frappe then serves a desk that cannot render: get_assets_json() reads
    ``assets/assets.json``, gets None from the missing file, and every
    ``{{ include_style(...) }}`` dies with "'NoneType' object has no attribute
    'get'" -- including the one in the error page rendered to report it, which
    is why the traceback nests four deep.

    Cheap to check and cheap to skip, so it runs on every invocation.
    """
    manifest = bench_root(args) / "sites" / "assets" / "assets.json"
    if manifest.exists():
        return
    cprint(f"{manifest.name} is missing; building assets ...", level=2)
    run_pilot(args, "--bench", args.bench_name, "build")
    if not manifest.exists():
        cprint(f"Build finished but {manifest} still does not exist", level=1)
        sys.exit(1)


def create_site_in_bench(args):
    app_names = [name for name, _, _ in apps_for_bench(args)]

    with redis_running(args):
        for site_name in all_site_names(args):
            provision_site(args, site_name, app_names)

        # Pilot has no equivalent of frappe/bench's `new-site --set-default`, so
        # every site would only answer to its own Host header. Without this,
        # http://localhost:<http_port> returns "localhost does not exist".
        # Written last: Pilot's own provisioning rewrites this file per site.
        set_common_site_config(args, {"default_site": args.site_name, "serve_default_site": True})

    ensure_assets_built(args)
    report_next_steps(args)


def report_next_steps(args):
    """What the operator still has to do by hand once provisioning is done."""
    # Read back rather than trusting args: on a re-run against an existing
    # bench, configure_bench never ran and bench.toml is the only truth.
    _, BenchConfig = import_pilot_config(args)
    config = BenchConfig.read(bench_root(args))
    sites = all_site_names(args)

    cprint("\nBench ready.", level=2)
    cprint(f"  start:    pilot -b {args.bench_name} start", level=2)
    cprint("            (the devcontainer postStartCommand does this for you)", level=3)
    cprint(f"  default:  http://localhost:{config.http_port}  ({args.site_name})", level=2)
    for site in sites:
        cprint(f"  site:     http://{site}:{config.http_port}/app", level=2)
    cprint(f"  admin UI: http://localhost:{config.admin.port}", level=2)
    cprint(f"  bench cmds: cd {os.getcwd()}/{args.bench_name}", level=2)

    # Every site on a bench shares one port and is picked out by Host header, so
    # the browser has to resolve each name. *.localhost maps to loopback on its
    # own; anything else needs a hosts entry on the *host* machine, not in this
    # container -- which is why this is printed rather than done.
    unresolvable = [site for site in sites if not site.endswith(".localhost")]
    if unresolvable:
        entries = "\n".join(f'  echo "127.0.0.1 {site}" | sudo tee -a /etc/hosts' for site in unresolvable)
        cprint(
            f"\nPilot links sites as http://<site>:{config.http_port}/desk, and only the"
            f"\ndefault site answers on plain localhost. For {', '.join(unresolvable)} to"
            f"\nresolve, run this on your host machine (not in the container):\n{entries}"
            f"\n\nNaming sites '<something>.localhost' avoids this entirely.",
            level=3,
        )


def repair_db_login_scope(args, site_name: str):
    """Grant the site's DB user access from any host.

    frappe's new-site scopes the user to the host the root connection came from
    (``SELECT USER()``), which in compose is the frappe container's IP and
    changes when containers are recreated. frappe/bench passed
    ``--mariadb-user-host-login-scope=%``; Pilot builds the new-site command
    itself and has no way to pass it, so the grant is widened afterwards.
    """
    if not args.db_login_scope or args.db_type != "mariadb":
        return

    site_config_path = bench_root(args) / "sites" / site_name / "site_config.json"
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
