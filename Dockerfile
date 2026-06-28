FROM zauberzeug/nicegui:latest

ARG PUID
ARG PGID

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
ENV UV_SYSTEM_PYTHON=1

WORKDIR /home/iot

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

RUN groupadd -g ${PGID} iot \
    && useradd -u ${PUID} -g ${PGID} -m iot \
    && chown -R ${PUID}:${PGID} /home/iot
USER iot

ENTRYPOINT ["uvicorn", "app.main:app", "--reload", "--log-level", "debug", "--host", "0.0.0.0", "--port", "8080", "--root-path", "/iot"]
