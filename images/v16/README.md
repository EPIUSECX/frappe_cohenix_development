# Cohenix Frappe v16 development image

Image: `ghcr.io/epiusecx/cohenix-frappe-dev:v16`

Build:

```bash
docker build -f images/v16/Dockerfile -t ghcr.io/epiusecx/cohenix-frappe-dev:v16 .
```

The Dockerfile installs prebuilt Python 3.14.2 (uv) and official Node 24
binaries. It does not compile CPython and does not include Python 3.10 or
Node 16.

CI builds, smoke-tests, and publishes amd64+arm64. See
`.github/workflows/image.yml`.
