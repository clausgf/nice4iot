FROM zauberzeug/nicegui:latest

WORKDIR /app
ARG PUID
ARG PGID
RUN groupadd -g ${PGID} iot \
    && useradd -u ${PUID} -g ${PGID} -m iot \
    && chown -R ${PUID}:${PGID} /app 
USER iot

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

WORKDIR /
ENTRYPOINT ["uvicorn", "app.main:app", "--reload", "--log-level", "debug", "--host", "0.0.0.0", "--port", "8080", "--root-path","/iot"]
