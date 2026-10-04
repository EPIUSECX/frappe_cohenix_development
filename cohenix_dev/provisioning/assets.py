"""Asset manifest recovery."""

from __future__ import annotations

from cohenix_dev.config import Settings
from cohenix_dev.errors import CohenixError
from cohenix_dev.output import cprint
from cohenix_dev.runtime.pilot import bench_root, run_pilot


def ensure_assets_built(settings: Settings) -> None:
    """Make sure sites/assets/assets.json exists.

    Pilot's SiteProvisioner.build_missing_assets() decides whether to build by
    asking whether sites/assets/<app> exists -- that directory is a symlink
    created by linking, so a bench can look complete without a desk bundle.
    """
    manifest = bench_root(settings) / "sites" / "assets" / "assets.json"
    if manifest.exists():
        return
    cprint(f"{manifest.name} is missing; building assets ...", level=2)
    run_pilot(settings, "--bench", settings.bench_name, "build")
    if not manifest.exists():
        raise CohenixError(f"Build finished but {manifest} still does not exist")
