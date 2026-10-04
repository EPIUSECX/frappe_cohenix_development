#!/bin/sh
# Fix volume ownership once the empty Docker volumes exist.
# Named volumes start as root:root; the image user is uid 1000.
set -eu

sudo -n chown -R frappe:frappe \
	/home/frappe/pilot \
	/home/frappe/.cache \
	/home/frappe/.npm \
	2>/dev/null || true

mkdir -p /home/frappe/pilot /home/frappe/.cache/uv /home/frappe/.cache/yarn /home/frappe/.npm
