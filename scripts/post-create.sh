#!/bin/sh
# Install the live workspace CLI and provision the development environment.
set -eu

/workspace/scripts/on-create.sh

python3 -m pip install --user --disable-pip-version-check -e /workspace
hash -r 2>/dev/null || true

if command -v pre-commit >/dev/null 2>&1; then
	:
else
	uv tool install pre-commit >/dev/null 2>&1 || python3 -m pip install --user pre-commit || true
fi

if [ -f /workspace/.pre-commit-config.yaml ]; then
	pre-commit install --install-hooks >/dev/null 2>&1 || true
fi

devctl sync
