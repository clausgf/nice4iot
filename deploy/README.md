# Deployment

Container images and Docker Compose examples for running nice4iot. All commands
are run from this `deploy/` directory. The image build context is the repository
root (the compose files set `context: ..`), so the same `Dockerfile` builds from
`pyproject.toml` / `uv.lock` / `app/`.

## Security note — read before exposing this

The management UI is **unauthenticated by default** (`AUTH_PROVIDER=none`), and
anyone who reaches it has full control over projects, devices, and tokens. The
standalone example therefore binds to `127.0.0.1` only.

Before putting nice4iot on a network:

- Set `AUTH_PROVIDER` to `password` (built-in login) or `proxy` (identity from a
  reverse proxy) — see the Authentication section of the top-level README.
- Set `NICEGUI_STORAGE_SECRET` to a long random value. The placeholder in these
  files is not a secret; with it, session cookies are forgeable.
- Terminate TLS at the proxy. Device tokens travel in `Authorization` headers
  and are bearer credentials.

## Scenarios

| File | Setup | Reached at |
|---|---|---|
| `docker-compose.yml` | Standalone, no proxy | `http://<host>:8080/` |
| `docker-compose.caddy.yml` | Behind Caddy, sub-path `/iot` | `http://<host>/iot/` |
| `docker-compose.caddy-epaper.yml` | Caddy + `/iot` + epaper extension | `http://<host>/iot/` |

```bash
# Create the state directory FIRST, owned by your user. If it is missing,
# Docker creates the bind-mount target as root and the container — which runs
# as PUID/PGID — cannot write to it ("mkdir: cannot create directory").
mkdir -p data

# 1) Standalone
docker compose up -d --build

# 2) Behind Caddy under /iot
docker compose -f docker-compose.caddy.yml up -d --build

# 3) Behind Caddy with the epaper extension
docker compose -f docker-compose.caddy-epaper.yml up -d --build
```

## Configuration

- **`NICEGUI_STORAGE_SECRET`** — set a long random value so UI sessions survive
  restarts. Every compose file has a placeholder; change it.
- **`PUID` / `PGID`** (build args) — the uid/gid the container runs as. Match
  the owner of the host `./data` directory to avoid permission errors.
- **`./data`** — bind-mounted to `/home/iot/data`; holds all project/device
  state. The entrypoint creates `data/projects` on first start (required, since
  `projects_dir` is validated to exist). Other settings come from environment
  variables — see the Configuration table in the top-level README.

## The `/iot` sub-path

Serving under a sub-path needs both halves to agree:

- **Caddy** strips the prefix — `handle_path /iot/* { reverse_proxy nice4iot:8080 }`.
- **nice4iot** is told its public prefix — `--root-path /iot` (set via the
  compose `command:` override), so NiceGUI emits `/iot`-prefixed asset,
  redirect, and WebSocket URLs.

To change the sub-path, edit both the `--root-path` value and the `Caddyfile`
path. For serving at the domain root, use the standalone scenario (no
`--root-path`).

## The epaper extension

[`nicepaper`](https://github.com/clausgf/nicepaper) is packaged as an optional
extra and is off by default; the epaper image adds
`INSTALL_EXTRAS="--extra epaper"`. It is a public `git+https` dependency, so the
build needs no credentials. Once installed the extension (`extensions.epaper`)
auto-registers; enable it per project under **Project → General → Extensions**.

## Notes

- **`MQTT connection error: [Errno 111] Connection refused — retrying in 5 s`**
  in the log is expected when no broker is running: MQTT ingest is enabled by
  default and points at `localhost:1883`. Point it at your broker, or switch it
  off, under **Settings → MQTT**.
- The image bakes `app/` in and installs the project, so `/docs` reports the
  real version (`app/main.py` reads it from the installed package metadata).
  Rebuild the image to ship code changes; for live-reload development run from
  source instead (`uv run uvicorn app.main:app --reload`, see the top-level
  README).
- These compose files are provided as configuration examples; validate the
  build in your own environment.
