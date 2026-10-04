#!/bin/sh
# Every container start: sync if needed, start Pilot, print doctor.
# Dev Container postStartCommand. Safe to re-run. No prompts.
set -eu

if [ -f /workspace/scripts/cohenix-lifecycle.sh ]; then
	. /workspace/scripts/cohenix-lifecycle.sh
else
	. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/cohenix-lifecycle.sh"
fi

cohenix_wait_for_mariadb
cohenix_sync
cohenix_start
cohenix_doctor
