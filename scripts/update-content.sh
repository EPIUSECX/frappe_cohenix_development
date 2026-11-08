#!/bin/sh
# Dev Container / Codespaces updateContentCommand.
# Runs during Codespaces prebuild creation and updates (MariaDB may not be ready).
# Keep this free of site provisioning; postCreate/postStart own sync/start.
set -eu

if [ -f /workspace/scripts/cohenix-lifecycle.sh ]; then
	. /workspace/scripts/cohenix-lifecycle.sh
else
	. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/cohenix-lifecycle.sh"
fi

cohenix_install_live_cli
cohenix_optional_precommit
