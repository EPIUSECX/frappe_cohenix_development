# Compatibility shim. The canonical v16 image is images/v16/Dockerfile.
# Building this file fails loudly so old scripts are updated instead of
# silently producing a legacy Python 3.10 / Node 16 image.

FROM debian:bookworm-slim
RUN printf '%s\n' \
    "resources/Dockerfile has moved." \
    "Build images/v16/Dockerfile instead:" \
    "  docker build -f images/v16/Dockerfile ." \
    >&2 \
    && exit 1
