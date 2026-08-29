# Multi-platform index digests verified against the official image registry on 2026-08-20.
ARG PYTHON_IMAGE=python:3.11.16-slim-bookworm@sha256:2e32f7d302adc1c37428355c1e646897c0c53f4fd60b6a551245fb90ee129f91
ARG NODE_IMAGE=node:24.19.0-bookworm-slim@sha256:3638d9a6fe4030bd716be989438248074489337ba3275657f93595428be4fc03
ARG JAVA_IMAGE=eclipse-temurin:21-jre-jammy@sha256:d63bd8d9b171999cbed8576f2c76e874dd4856791a358536e5c4d407e77edc13
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1
ARG DEBIAN_SNAPSHOT=20260803T000000Z
ARG R5_JAR_URL=https://github.com/r5py/r5/releases/download/v7.5.1-r5py/r5-v7.5.1-r5py-all.jar
ARG R5_JAR_SHA256=d50be106cadd7b636cfc0e209052767d7df570629f79fdf98ecd5cf5d2d89be7

FROM ${NODE_IMAGE} AS web-build

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
COPY documentation/methodology/methodology.md /documentation/methodology/methodology.md
RUN npm run lint
RUN npm run typecheck
RUN npm test
RUN npm run build

FROM ${JAVA_IMAGE} AS java-runtime

FROM ${UV_IMAGE} AS uv-runtime

FROM ${PYTHON_IMAGE} AS python-environment

ARG R5_JAR_URL
ARG R5_JAR_SHA256

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=uv-runtime /uv /uvx /bin/
WORKDIR /opt/ciw
COPY pyproject.toml uv.lock .python-version README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable --python /usr/local/bin/python3.11
RUN python -c "import hashlib,pathlib,urllib.request; path=pathlib.Path('/opt/r5/r5-v7.5.1-r5py-all.jar'); path.parent.mkdir(parents=True,exist_ok=True); urllib.request.urlretrieve('${R5_JAR_URL}',path); actual=hashlib.sha256(path.read_bytes()).hexdigest(); assert actual=='${R5_JAR_SHA256}', f'R5 JAR checksum mismatch: {actual}'"

FROM ${PYTHON_IMAGE} AS analysis-runtime

ARG DEBIAN_SNAPSHOT

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    JAVA_HOME=/opt/java/openjdk \
    VIRTUAL_ENV=/opt/ciw/.venv \
    PATH=/opt/ciw/.venv/bin:/opt/java/openjdk/bin:$PATH

RUN sed -i \
      -e "s|URIs: http://deb.debian.org/debian$|URIs: http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|" \
      -e "s|URIs: http://deb.debian.org/debian-security$|URIs: http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|" \
      /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Check-Valid-Until=false update \
    && apt-get install --yes --no-install-recommends \
      gdal-bin=3.6.2+dfsg-1+b2 \
      osmium-tool=1.15.0-1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system ciw \
    && useradd --system --gid ciw --create-home --home-dir /home/ciw ciw

WORKDIR /workspace
COPY --from=java-runtime /opt/java/openjdk /opt/java/openjdk
COPY --from=python-environment /opt/ciw/.venv /opt/ciw/.venv
COPY --from=python-environment /opt/r5 /opt/r5
COPY third_party/r5 /opt/licenses/r5
COPY third_party/r5py /opt/licenses/r5py
COPY configs/r5py.yml /etc/r5py.yml
COPY --chown=ciw:ciw configs ./configs
COPY --chown=ciw:ciw schemas ./schemas
COPY --from=web-build --chown=ciw:ciw /web/dist ./web/dist

USER ciw
VOLUME ["/workspace/data", "/workspace/runs", "/workspace/exports"]
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD ["ciw", "validate", "--config", "configs/auckland.yml", "--config-only"]
ENTRYPOINT ["ciw"]
CMD ["--help"]

FROM analysis-runtime AS complete-toolchain

USER root
COPY --from=web-build /usr/local/bin/node /usr/local/bin/node
COPY --from=web-build /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY --from=web-build --chown=ciw:ciw /web /opt/ciw-web
COPY --from=web-build --chown=ciw:ciw /documentation /opt/documentation
USER ciw
