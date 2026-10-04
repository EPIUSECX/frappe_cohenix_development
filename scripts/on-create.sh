#!/bin/sh
# Fix volume ownership once the empty Docker volumes exist.
# Named volumes start as root:root; the image user is uid 1000.
set -eu

sudo -n chown -R frappe:frappe \
	/home/frappe/pilot \
	/home/frappe/.cache \
	/home/frappe/.npm \
	2>/dev/null || true

# GHA and some cloud agents mount /workspace as another uid. Change only the
# directory inode and `.cohenix/` so the runner can still write CI artifacts.
if [ -d /workspace ] && [ ! -w /workspace ]; then
	sudo -n chown frappe:frappe /workspace
	sudo -n mkdir -p /workspace/.cohenix
	sudo -n chown -R frappe:frappe /workspace/.cohenix
fi

mkdir -p /home/frappe/pilot /home/frappe/.cache/uv /home/frappe/.cache/yarn /home/frappe/.npm
