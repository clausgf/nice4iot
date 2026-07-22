# Deployment

A container image ([`Dockerfile`](Dockerfile)) and one Docker Compose example
([`docker-compose.yml`](docker-compose.yml)) for running nice4iot behind a
reverse proxy. Run the commands below from this `deploy/` directory; the image
build context is the repository root (the compose file sets `context: ..`).

```bash
mkdir -p data          # once, owned by your user — see the permissions note below
docker compose up -d --build
```

**Deploying from your own directory** (e.g. next to your other services'
compose files) is usually cleaner than running from inside the checkout. Copy
`docker-compose.yml` into that directory and point `build.context` at your
cloned nice4iot repo — an absolute path, since it is no longer `..`:

```yaml
    build:
      context: /home/you/git/nice4iot        # path to the cloned repo
      dockerfile: deploy/Dockerfile
```

Then `mkdir -p data` there and `docker compose up -d --build` from that
directory; `git pull` in the repo and rebuild to update.

The example does not publish nice4iot itself: it joins an external `proxy`
Docker network and only `expose`s port 8080 to that network, so a reverse proxy
(Caddy, Traefik, nginx, …) on the same network is the sole public entry point.

## Security note — read before exposing this

The management UI is **unauthenticated by default** (`AUTH_PROVIDER=none`); anyone
who reaches it has full control over projects, devices, and tokens. Before it is
reachable from anywhere untrusted:

- Set `AUTH_PROVIDER` to `password` (built-in login) or `proxy` (identity from the
  reverse proxy) — see [docs/configuration.md](../docs/configuration.md#authentication).
- Set `NICEGUI_STORAGE_SECRET` to a long random value. The placeholder in the
  compose file is not a secret; with it, session cookies are forgeable.
- Terminate TLS at the proxy. Device tokens travel in `Authorization` headers and
  are bearer credentials.

### Two auth domains — don't lock out the devices

nice4iot has two independent authentication paths, and they must not be conflated:

- **Admin UI** (the NiceGUI pages) — for humans; guarded by `AUTH_PROVIDER`
  (off by default), which you must turn on before exposing it.
- **Device API** (`/api/*`) — for devices; already authenticated by per-device
  **bearer tokens**. It needs no extra network auth, only TLS.

The trap: if you protect the UI with a *blanket* proxy auth (e.g. oauth2-proxy in
front of the whole app), it will also block `/api/*` and lock out every device.
**Exempt `/api/*` from the proxy's login gate** so devices can still provision
and push data; only the UI paths should require a human login. (If an external
load balancer polls `/health` *through* the proxy, exempt that too — the
container's own healthcheck hits the app directly and is unaffected.)

## Configuration

Every setting is an environment variable — **full reference:
[docs/configuration.md](../docs/configuration.md)**. Set any of them under
`environment:` in [`docker-compose.yml`](docker-compose.yml). The
deployment-specific knobs:

- **`NICEGUI_STORAGE_SECRET`** — long random value so UI sessions survive
  restarts. The compose file ships a placeholder; change it.
- **`PUID` / `PGID`** (build args) — the uid/gid the container runs as. Match the
  owner of the host `./data` directory.
- **`./data`** — bind-mounted to `/home/iot/data`; holds all project/device
  state. The entrypoint creates `data/projects` on first start.

**Permissions:** create `./data` **before** the first start, owned by your user.
If it is missing, Docker creates the bind-mount target as root and the container
— which runs as `PUID`/`PGID` — cannot write to it (`mkdir: cannot create
directory 'data/projects': Permission denied`).

## Serving under a sub-path

Served at the domain root by default. To serve under a sub-path (e.g. `/iot`),
both halves must agree:

- **The proxy** strips the prefix. Caddy:

  ```
  handle_path /iot/* {
      reverse_proxy nice4iot:8080
  }
  ```

- **nice4iot** is told its public prefix — switch to the `--root-path /iot`
  `command:` line in `docker-compose.yml`, so NiceGUI emits `/iot`-prefixed
  asset, redirect, and WebSocket URLs.

## The epaper extension

The compose file builds with `INSTALL_EXTRAS="--extra epaper"` **by default**,
pulling in [`nicepaper`](https://github.com/clausgf/nicepaper) (a public
`git+https` dependency — no credentials). Comment that build arg out to build
without it. Once installed the extension (`extensions.epaper`) auto-registers;
enable it per project under **Project → General → Extensions**.

## Notes

- **Healthcheck:** the image ships a `HEALTHCHECK` that polls `/health` inside the
  container, so `docker ps` shows healthy/unhealthy and Compose can restart on
  failure or gate `depends_on: { condition: service_healthy }`. It runs directly
  against the app, so it is independent of the reverse proxy and `--root-path`.
- **MQTT** is **off by default** (`MQTT_ENABLED=false`). If you enable it but the
  broker isn't reachable yet, the log shows `MQTT connection error … retrying`
  until it comes up — that is expected, not a failure of nice4iot.
- The image bakes `app/` in and installs the project, so `/docs` reports the real
  version. Rebuild the image to ship code changes; for live-reload development run
  from source (`uv run uvicorn app.main:app --reload`, see the top-level README).
- This compose file is an example; validate the build in your own environment.
