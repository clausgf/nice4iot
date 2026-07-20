# syntax=docker/dockerfile:1
#
# nice4iot production image.
#
# The build context is the repository ROOT (the compose files here already set
# `context: ..`). To build by hand:
#     docker build -f deploy/Dockerfile -t nice4iot ..
#
# To include the epaper extension, build with INSTALL_EXTRAS="--extra epaper"
# (see the docker-compose.caddy-epaper.yml example and deploy/README.md).
FROM zauberzeug/nicegui:latest

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ARG PUID=1000
ARG PGID=1000
ARG INSTALL_EXTRAS=""

# Install into the base image's Python environment rather than a project venv,
# so the image keeps one interpreter and `uvicorn` resolves to the same
# environment the dependencies were synced into.
ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

WORKDIR /home/iot

# git is required by uv to fetch the git-sourced dependencies (niceview, and
# nicepaper when the extra is enabled). Both are public https:// sources, so
# no credentials or ssh client are needed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# 1) Dependencies only — this layer is cached unless pyproject.toml/uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project ${INSTALL_EXTRAS}

# 2) Application code, then install the project itself so importlib.metadata can
#    report its version (surfaced at /docs).
COPY app ./app
RUN uv sync --frozen --no-dev ${INSTALL_EXTRAS}

COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && groupadd -g ${PGID} iot \
    && useradd -u ${PUID} -g ${PGID} -d /home/iot iot \
    && chown -R ${PUID}:${PGID} /home/iot
USER iot

EXPOSE 8080

# entrypoint.sh creates the projects directory (required at startup) then execs
# the command. Root-path is unset here (served at /); the Caddy scenarios add
# `--root-path /iot` via a command override. No --reload in production.
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
