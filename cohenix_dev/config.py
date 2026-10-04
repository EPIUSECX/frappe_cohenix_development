"""Load toolchain.toml, profiles, checksums, and runtime settings."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomllib

from cohenix_dev.errors import ConfigError

SAFE_SQL_IDENTIFIER = __import__("re").compile(r"^[A-Za-z0-9_]+$")

DEFAULT_HTTP_PORT = 8000
DEFAULT_SOCKETIO_PORT = 9000
DEFAULT_ADMIN_PORT = 8002
APP_HISTORY_DEPTH = 200
SHALLOW_CLONE_MAX_COMMITS = 50
PILOT_CLI_DEPS = ["packaging", "pymysql"]
ADMIN_DEPS_FALLBACK = [
    "flask>=3.0",
    "psutil>=5.9",
    "pymysql>=1.1",
    "gunicorn>=21.2",
    "pyjwt[crypto]>=2.8",
]
PILOT_RELEASES_URL = "https://api.github.com/repos/frappe/pilot/releases?per_page=1"
PILOT_RELEASE_DOWNLOAD_URL = "https://github.com/frappe/pilot/releases/download/{version}/pilot.tar.gz"
BENCH_SHIM_MARKER = "# pilot-bench-shim v1"
PROVISIONER_SCHEMA = 2


def repo_root() -> Path:
    here = Path(__file__).resolve().parent.parent
    if (here / "toolchain.toml").exists():
        return here
    workspace = Path(os.environ.get("COHENIX_WORKSPACE", "/workspace"))
    if (workspace / "toolchain.toml").exists():
        return workspace
    cwd = Path.cwd()
    if (cwd / "toolchain.toml").exists():
        return cwd
    return here


def find_file(*relative: str) -> Path:
    root = repo_root()
    path = root.joinpath(*relative)
    if path.exists():
        return path
    fallback = Path("/etc/cohenix").joinpath(*relative)
    if fallback.exists():
        return fallback
    return path


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Missing configuration file: {path}")
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_toolchain(path: Path | None = None) -> dict[str, Any]:
    return load_toml(path or find_file("toolchain.toml"))


def load_checksums(path: Path | None = None) -> dict[str, Any]:
    candidate = path or find_file("config", "checksums.toml")
    if not candidate.exists():
        return {}
    return load_toml(candidate)


def load_profiles_doc(path: Path | None = None) -> dict[str, Any]:
    return load_toml(path or find_file("config", "profiles.toml"))


@dataclass(frozen=True)
class AppSpec:
    name: str
    repo: str
    branch: str

    def key(self) -> tuple[str, str, str]:
        return (self.name, self.repo, self.branch)

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "repo": self.repo, "branch": self.branch}


def _app_from_mapping(data: dict[str, Any], default_branch: str) -> AppSpec:
    repo = str(data.get("repo") or data.get("url") or "")
    if not repo:
        raise ConfigError(f"App entry is missing repo/url: {data!r}")
    name = str(data.get("name") or repo.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git"))
    branch = str(data.get("branch") or default_branch)
    return AppSpec(name=name, repo=repo, branch=branch)


def resolve_profile(
    name: str,
    *,
    profiles_doc: dict[str, Any] | None = None,
    default_branch: str = "version-16",
) -> list[AppSpec]:
    doc = profiles_doc or load_profiles_doc()
    profiles = doc.get("profiles") or {}
    if name not in profiles:
        known = ", ".join(sorted(profiles))
        raise ConfigError(f"Unknown profile {name!r}. Known profiles: {known}")
    return _resolve_profile_chain(name, profiles, default_branch, seen=set())


def _resolve_profile_chain(
    name: str,
    profiles: dict[str, Any],
    default_branch: str,
    seen: set[str],
) -> list[AppSpec]:
    if name in seen:
        raise ConfigError(f"Profile cycle involving {name!r}")
    seen.add(name)
    profile = profiles[name]
    apps: list[AppSpec] = []
    parent = profile.get("extends")
    if parent:
        if parent not in profiles:
            raise ConfigError(f"Profile {name!r} extends unknown profile {parent!r}")
        apps.extend(_resolve_profile_chain(parent, profiles, default_branch, seen))
    by_name = {app.name: i for i, app in enumerate(apps)}
    for raw in profile.get("apps") or []:
        spec = _app_from_mapping(raw, default_branch)
        if spec.name in by_name:
            apps[by_name[spec.name]] = spec
        else:
            by_name[spec.name] = len(apps)
            apps.append(spec)
    return apps


def apps_from_json(path: Path, default_branch: str, frappe_repo: str, frappe_branch: str) -> list[AppSpec]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    apps = [AppSpec("frappe", frappe_repo, frappe_branch)]
    for entry in entries:
        spec = _app_from_mapping(entry, default_branch)
        if spec.name == "frappe":
            apps[0] = AppSpec("frappe", spec.repo, spec.branch)
            continue
        apps.append(spec)
    return apps


def overlay_apps(path: Path, current: list[AppSpec], default_branch: str) -> list[AppSpec]:
    if not path.exists():
        return current
    data = load_toml(path) if path.suffix == ".toml" else {"apps": json.loads(path.read_text())}
    apps = list(current)
    by_name = {app.name: i for i, app in enumerate(apps)}
    for raw in data.get("apps") or []:
        spec = _app_from_mapping(raw, default_branch)
        if spec.name in by_name:
            apps[by_name[spec.name]] = spec
        else:
            by_name[spec.name] = len(apps)
            apps.append(spec)
    for name in data.get("remove") or []:
        apps = [app for app in apps if app.name != name]
        by_name = {app.name: i for i, app in enumerate(apps)}
    return apps


def list_profile_names(profiles_doc: dict[str, Any] | None = None) -> list[str]:
    doc = profiles_doc or load_profiles_doc()
    return sorted((doc.get("profiles") or {}).keys())


@dataclass
class Settings:
    bench_name: str = "development-bench"
    site_name: str = "cohenix.localhost"
    extra_sites: list[str] = field(default_factory=list)
    frappe_repo: str = "https://github.com/frappe/frappe"
    frappe_branch: str = "version-16"
    py_version: str = "3.14"
    node_version: str | None = None
    verbose: bool = False
    admin_password: str = "admin"
    db_type: str = "mariadb"
    db_root_username: str = "root"
    db_root_password: str = "123"
    db_host: str | None = None
    db_port: int | None = None
    db_login_scope: str = "%"
    pilot_dir: str = "/home/frappe/pilot"
    pilot_version: str = "v0.0.23-pre-alpha"
    http_port: int = DEFAULT_HTTP_PORT
    socketio_port: int = DEFAULT_SOCKETIO_PORT
    admin_port: int = DEFAULT_ADMIN_PORT
    admin_ui_password: str | None = None
    profile: str = "hr"
    apps_json: str | None = None
    workspace: str = "/workspace"
    yes: bool = False
    prune: bool = False

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace)

    @property
    def overlay_path(self) -> Path:
        return self.workspace_path / ".cohenix" / "apps.overlay.toml"

    @property
    def local_config_path(self) -> Path:
        return self.workspace_path / ".cohenix" / "config.toml"

    def apps(self) -> list[AppSpec]:
        if self.apps_json:
            apps = apps_from_json(
                Path(self.apps_json),
                self.frappe_branch,
                self.frappe_repo,
                self.frappe_branch,
            )
        else:
            apps = resolve_profile(self.profile, default_branch=self.frappe_branch)
            if apps and apps[0].name == "frappe":
                apps[0] = AppSpec("frappe", self.frappe_repo, self.frappe_branch)
            elif not any(app.name == "frappe" for app in apps):
                apps.insert(0, AppSpec("frappe", self.frappe_repo, self.frappe_branch))
        return overlay_apps(self.overlay_path, apps, self.frappe_branch)

    def site_names(self) -> list[str]:
        names = [self.site_name]
        names += [name for name in self.extra_sites if name not in names]
        return names


def _local_profile(workspace: Path) -> str | None:
    path = workspace / ".cohenix" / "config.toml"
    if not path.exists():
        return None
    data = load_toml(path)
    value = data.get("profile")
    return str(value) if value else None


def settings_from_env(overrides: dict[str, Any] | None = None) -> Settings:
    toolchain = load_toolchain()
    defaults = toolchain.get("defaults") or {}
    python = toolchain.get("python") or {}
    frappe = toolchain.get("frappe") or {}
    pilot = toolchain.get("pilot") or {}
    workspace = Path(os.environ.get("COHENIX_WORKSPACE", defaults.get("workspace", "/workspace")))
    if not workspace.exists():
        workspace = Path.cwd()
    profile = (
        os.environ.get("COHENIX_PROFILE")
        or _local_profile(workspace)
        or defaults.get("profile")
        or "hr"
    )
    settings = Settings(
        bench_name=os.environ.get("BENCH_NAME", defaults.get("bench_name", "development-bench")),
        site_name=os.environ.get("SITE_NAME", defaults.get("site_name", "cohenix.localhost")),
        frappe_repo=os.environ.get("FRAPPE_REPO", frappe.get("repo", "https://github.com/frappe/frappe")),
        frappe_branch=os.environ.get("FRAPPE_BRANCH", frappe.get("branch", "version-16")),
        py_version=os.environ.get("PYTHON_VERSION", python.get("version", "3.14.2")),
        node_version=os.environ.get("NODE_VERSION"),
        admin_password=os.environ.get("ADMIN_PASSWORD", defaults.get("admin_password", "admin")),
        db_root_password=os.environ.get("DB_ROOT_PASSWORD", defaults.get("db_root_password", "123")),
        pilot_dir=os.environ.get("PILOT_DIR", defaults.get("pilot_dir", "/home/frappe/pilot")),
        pilot_version=os.environ.get("PILOT_VERSION", pilot.get("version", "v0.0.23-pre-alpha")),
        http_port=int(os.environ.get("HTTP_PORT", defaults.get("http_port", DEFAULT_HTTP_PORT))),
        socketio_port=int(os.environ.get("SOCKETIO_PORT", defaults.get("socketio_port", DEFAULT_SOCKETIO_PORT))),
        admin_port=int(os.environ.get("ADMIN_PORT", defaults.get("admin_port", DEFAULT_ADMIN_PORT))),
        profile=profile,
        apps_json=os.environ.get("COHENIX_APPS_JSON") or os.environ.get("APPS_JSON"),
        workspace=str(workspace),
    )
    if overrides:
        for key, value in overrides.items():
            if value is None:
                continue
            setattr(settings, key, value)
    if settings.pilot_version == "latest" and not os.environ.get("COHENIX_ALLOW_PILOT_LATEST"):
        raise ConfigError(
            "PILOT_VERSION=latest is not allowed on the normal path. "
            "Set an explicit tag, or COHENIX_ALLOW_PILOT_LATEST=1 for a controlled experiment."
        )
    return settings


def write_local_profile(workspace: Path, profile: str) -> Path:
    resolve_profile(profile)
    path = workspace / ".cohenix" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        existing = load_toml(path)
    existing["profile"] = profile
    # tomllib is read-only; write a small TOML subset.
    lines = [f'profile = "{profile}"\n']
    for key, value in existing.items():
        if key == "profile":
            continue
        if isinstance(value, str):
            lines.append(f'{key} = "{value}"\n')
        elif isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}\n")
        elif isinstance(value, int | float):
            lines.append(f"{key} = {value}\n")
    path.write_text("".join(lines), encoding="utf-8")
    return path


def image_ref(toolchain: dict[str, Any] | None = None) -> str:
    data = toolchain or load_toolchain()
    image = data["image"]
    return f"{image['registry']}/{image['name']}:{image['tag']}"


def toolchain_versions() -> dict[str, str]:
    data = load_toolchain()
    return {
        "python": data["python"]["version"],
        "node": data["node"]["version"],
        "yarn": data["node"]["yarn"],
        "uv": data["uv"]["version"],
        "pilot": data["pilot"]["version"],
        "bench": data["bench"]["ref"],
        "frappe_branch": data["frappe"]["branch"],
        "mariadb_image": data["database"]["mariadb_image"],
        "image": image_ref(data),
    }
