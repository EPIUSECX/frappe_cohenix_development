#!/usr/bin/env python3
"""Compatibility wrapper. Prefer `devctl`.

python installer.py
    is equivalent to
devctl sync

python installer.py --verify-only
    is equivalent to
devctl verify
"""

from __future__ import annotations

import sys

from cohenix_dev.compat import installed_pilot_version, main, pilot_release_asset


if __name__ == "__main__":
    sys.exit(main())
