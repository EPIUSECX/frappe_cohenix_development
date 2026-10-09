#!/bin/sh
# One-time Dev Container setup: volume ownership, live CLI, first provision.
# postCreateCommand. `devctl start` and `devctl doctor` run on every start.
set -eu

/workspace/scripts/on-create.sh

if [ -f /workspace/scripts/cohenix-lifecycle.sh ]; then
	. /workspace/scripts/cohenix-lifecycle.sh
else
	. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/cohenix-lifecycle.sh"
fi

cohenix_install_live_cli
cohenix_optional_precommit
cohenix_wait_for_mariadb
cohenix_sync
