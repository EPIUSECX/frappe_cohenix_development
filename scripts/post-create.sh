#!/bin/sh
# Install the live workspace CLI and provision the development environment.
set -eu

/workspace/scripts/on-create.sh

PYTHON="${VIRTUAL_ENV:+$VIRTUAL_ENV/bin/python}"
PYTHON="${PYTHON:-$(command -v python3)}"
uv pip install --python "$PYTHON" -e /workspace
hash -r 2>/dev/null || true

# pre-commit is editor convenience, not required to provision a site.
if command -v pre-commit >/dev/null 2>&1; then
	:
else
	uv tool install pre-commit >/dev/null 2>&1 || echo "pre-commit not installed (optional)"
fi

if [ -f /workspace/.pre-commit-config.yaml ]; then
	pre-commit install --install-hooks >/dev/null 2>&1 || true
fi

devctl sync
