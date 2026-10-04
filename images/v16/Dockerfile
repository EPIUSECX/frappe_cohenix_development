# Cohenix Frappe v16 development image.
# Canonical definition. Compose and CI build this file.
#
# ARG defaults must match toolchain.toml. CI overwrites them via --build-arg.
# This image installs prebuilt CPython (uv) and official Node binaries.
# It does not compile Python with pyenv and does not install legacy 3.10/Node 16.

ARG UV_VERSION=0.11.33
FROM debian:bookworm-slim AS uv-fetch
ARG UV_VERSION=0.11.33
ARG TARGETARCH
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && ARCH="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && if [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then UV_ARCH=aarch64; else UV_ARCH=x86_64; fi \
    && curl -fsSL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${UV_ARCH}-unknown-linux-gnu.tar.gz" \
        -o "/tmp/uv-${UV_ARCH}-unknown-linux-gnu.tar.gz" \
    && curl -fsSL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${UV_ARCH}-unknown-linux-gnu.tar.gz.sha256" \
        -o "/tmp/uv-${UV_ARCH}-unknown-linux-gnu.tar.gz.sha256" \
    && cd /tmp && sha256sum -c "uv-${UV_ARCH}-unknown-linux-gnu.tar.gz.sha256" \
    && tar -xzf "/tmp/uv-${UV_ARCH}-unknown-linux-gnu.tar.gz" -C /tmp \
    && mv /tmp/uv-${UV_ARCH}-unknown-linux-gnu/uv /uv \
    && chmod +x /uv

FROM debian:bookworm-slim AS cohenix-v16

LABEL org.opencontainers.image.title="Cohenix Frappe v16 development image" \
      org.opencontainers.image.source="https://github.com/EPIUSECX/frappe_cohenix_development" \
      org.opencontainers.image.description="Prebuilt Frappe v16 toolchain for Cohenix developers, CI, and coding agents"

ARG PYTHON_VERSION=3.14.2
ARG NODE_VERSION=24.12.0
ARG YARN_VERSION=1.22.22
ARG UV_VERSION=0.11.33
ARG BENCH_REPO=https://github.com/frappe/bench.git
ARG BENCH_REF=v5.31.0
ARG PILOT_VERSION=v0.0.23-pre-alpha
ARG WKHTMLTOPDF_VERSION=0.12.6.1-3
ARG WKHTMLTOPDF_DISTRO=bookworm
ARG COHENIX_IMAGE_TAG=v16

ENV PYTHON_VERSION=${PYTHON_VERSION} \
    NODE_VERSION=${NODE_VERSION} \
    YARN_VERSION=${YARN_VERSION} \
    UV_VERSION=${UV_VERSION} \
    PILOT_VERSION=${PILOT_VERSION} \
    COHENIX_IMAGE_TAG=${COHENIX_IMAGE_TAG} \
    COHENIX_IMAGE_REF=ghcr.io/epiusecx/cohenix-frappe-dev:${COHENIX_IMAGE_TAG} \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8 \
    UV_PYTHON_INSTALL_DIR=/home/frappe/.local/share/uv/python \
    UV_CACHE_DIR=/home/frappe/.cache/uv \
    YARN_CACHE_FOLDER=/home/frappe/.cache/yarn \
    npm_config_cache=/home/frappe/.npm \
    VIRTUAL_ENV=/home/frappe/.local/share/cohenix-python \
    PATH=/home/frappe/.local/share/cohenix-python/bin:/home/frappe/.local/bin:/usr/local/bin:$PATH \
    BENCH_DEVELOPER=1 \
    SHELL=/bin/bash

LABEL dev.cohenix.python=${PYTHON_VERSION} \
      dev.cohenix.node=${NODE_VERSION} \
      dev.cohenix.uv=${UV_VERSION} \
      dev.cohenix.bench=${BENCH_REF} \
      dev.cohenix.pilot=${PILOT_VERSION} \
      dev.cohenix.image=${COHENIX_IMAGE_TAG}

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y \
        ca-certificates \
        git \
        mariadb-client \
        postgresql-client \
        gettext-base \
        wget \
        curl \
        xz-utils \
        gnupg \
        libssl-dev \
        fonts-cantarell \
        xfonts-75dpi \
        xfonts-base \
        libpango-1.0-0 \
        libharfbuzz0b \
        libpangoft2-1.0-0 \
        libpangocairo-1.0-0 \
        locales \
        build-essential \
        cron \
        vim \
        sudo \
        iputils-ping \
        watch \
        tree \
        nano \
        less \
        bash-completion \
        jq \
        procps \
        psmisc \
        libpq-dev \
        libffi-dev \
        liblcms2-dev \
        libldap2-dev \
        libmariadb-dev \
        libsasl2-dev \
        libtiff5-dev \
        libwebp-dev \
        pkg-config \
        redis-tools \
        redis-server \
        rlwrap \
        tk8.6-dev \
        ssh-client \
        net-tools \
        make \
        libbz2-dev \
        libsqlite3-dev \
        zlib1g-dev \
        libreadline-dev \
        llvm \
        libncurses5-dev \
        libncursesw5-dev \
        tk-dev \
        liblzma-dev \
        file \
        media-types \
        python3 \
    && rm -rf /var/lib/apt/lists/* \
    && sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen \
    && dpkg-reconfigure --frontend=noninteractive locales \
    && update-locale LANG=en_US.UTF-8

COPY config/checksums.toml /tmp/checksums.toml
COPY images/v16/verify_checksum.py /tmp/verify_checksum.py

RUN ARCH="$(dpkg --print-architecture)" \
    && downloaded_file="wkhtmltox_${WKHTMLTOPDF_VERSION}.${WKHTMLTOPDF_DISTRO}_${ARCH}.deb" \
    && wget -q "https://github.com/wkhtmltopdf/packaging/releases/download/${WKHTMLTOPDF_VERSION}/${downloaded_file}" \
    && python3 /tmp/verify_checksum.py wkhtmltopdf "$downloaded_file" \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y "./${downloaded_file}" \
    && rm -f "$downloaded_file" \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 frappe \
    && useradd --no-log-init -r -m -u 1000 -g 1000 -G sudo frappe \
    && echo "frappe ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

COPY --from=uv-fetch /uv /usr/local/bin/uv

USER frappe
WORKDIR /home/frappe

RUN mkdir -p /home/frappe/.local/bin \
        /home/frappe/.cache/uv \
        /home/frappe/.cache/yarn \
        /home/frappe/.npm \
        /home/frappe/pilot \
    && uv python install "${PYTHON_VERSION}" \
    && uv venv "${VIRTUAL_ENV}" --python "${PYTHON_VERSION}" \
    && printf '%s\n' '#!/bin/sh' "exec ${VIRTUAL_ENV}/bin/python \"\$@\"" > /home/frappe/.local/bin/python \
    && printf '%s\n' '#!/bin/sh' "exec ${VIRTUAL_ENV}/bin/python3 \"\$@\"" > /home/frappe/.local/bin/python3 \
    && chmod +x /home/frappe/.local/bin/python /home/frappe/.local/bin/python3 \
    && uv pip install --python "${VIRTUAL_ENV}/bin/python" pip virtualenv packaging pymysql \
    && echo "export VIRTUAL_ENV=${VIRTUAL_ENV}" >> /home/frappe/.bashrc \
    && echo "export PATH=${VIRTUAL_ENV}/bin:/home/frappe/.local/bin:/usr/local/bin:\$PATH" >> /home/frappe/.bashrc \
    && echo "export PATH=${VIRTUAL_ENV}/bin:/home/frappe/.local/bin:/usr/local/bin:\$PATH" >> /home/frappe/.profile \
    && echo "export BENCH_DEVELOPER=1" >> /home/frappe/.bashrc \
    && echo "export UV_CACHE_DIR=/home/frappe/.cache/uv" >> /home/frappe/.bashrc \
    && echo "export YARN_CACHE_FOLDER=/home/frappe/.cache/yarn" >> /home/frappe/.bashrc \
    && echo "export npm_config_cache=/home/frappe/.npm" >> /home/frappe/.bashrc \
    && echo "export PILOT_DIR=/home/frappe/pilot" >> /home/frappe/.bashrc \
    && echo "export PILOT_DIR=/home/frappe/pilot" >> /home/frappe/.profile

RUN NODE_ARCH="$(uname -m)" \
    && if [ "$NODE_ARCH" = "aarch64" ]; then NODE_DIST=linux-arm64; else NODE_DIST=linux-x64; fi \
    && curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-${NODE_DIST}.tar.xz" \
    && curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" \
    && grep "node-v${NODE_VERSION}-${NODE_DIST}.tar.xz" SHASUMS256.txt | sha256sum -c - \
    && sudo tar -xJf "node-v${NODE_VERSION}-${NODE_DIST}.tar.xz" -C /usr/local --strip-components=1 \
    && rm -f "node-v${NODE_VERSION}-${NODE_DIST}.tar.xz" SHASUMS256.txt \
    && sudo npm install -g "yarn@${YARN_VERSION}" \
    && node --version \
    && yarn --version

RUN git clone "${BENCH_REPO}" --depth 1 -b "${BENCH_REF}" /home/frappe/.bench \
    && uv pip install --python "${VIRTUAL_ENV}/bin/python" --no-cache -e /home/frappe/.bench

USER root
COPY pyproject.toml /opt/cohenix/pyproject.toml
COPY cohenix_dev /opt/cohenix/cohenix_dev
COPY toolchain.toml /opt/cohenix/toolchain.toml
COPY config /opt/cohenix/config
RUN mkdir -p /etc/cohenix \
    && cp /opt/cohenix/toolchain.toml /etc/cohenix/toolchain.toml \
    && cp -a /opt/cohenix/config /etc/cohenix/config \
    && chown -R frappe:frappe /etc/cohenix /opt/cohenix
USER frappe

RUN uv pip install --python "${VIRTUAL_ENV}/bin/python" --no-cache /opt/cohenix \
    && python3 -c "import cohenix_dev; print(cohenix_dev.__version__)" \
    && devctl --help >/dev/null

WORKDIR /workspace

EXPOSE 8000-8005 9000-9005 6787 8002

FROM cohenix-v16 AS cohenix-v16-test
RUN python3 --version \
    && node --version \
    && npm --version \
    && yarn --version \
    && uv --version \
    && command -v bench \
    && python3 -c "import bench, packaging, pymysql" \
    && redis-server --version \
    && mariadb --version \
    && test ! -d /home/frappe/.pyenv \
    && python3 -c "import sys; assert sys.version_info[:2] == (3, 14), sys.version" \
    && python3 -c "import sys; assert 'cohenix-python' in sys.prefix, sys.prefix"
RUN bash -lc "python3 --version && node --version && yarn --version && command -v bench && command -v devctl && devctl --help >/dev/null"
