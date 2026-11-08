#!/bin/sh
# One-time Dev Container setup: ownership + first provision.
# postCreateCommand (not run during Codespaces prebuild creation).
# Live CLI install lives in update-content.sh so prebuilds bake it.
# `devctl start` and `devctl doctor` run on every start.
set -eu

/workspace/scripts/on-create.sh

# Idempotent if updateContent already ran; harmless if it did not.
/workspace/scripts/update-content.sh

if [ -f /workspace/scripts/cohenix-lifecycle.sh ]; then
	. /workspace/scripts/cohenix-lifecycle.sh
else
	. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/cohenix-lifecycle.sh"
fi

cohenix_wait_for_mariadb
cohenix_sync
