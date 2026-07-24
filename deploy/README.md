# Deployment

A container image ([`Dockerfile`](Dockerfile)) and three Docker Compose files,
each for a different way of running nice4iot. Run the commands below from this
`deploy/` directory.

| File | Use it when | Image |
|---|---|---|
| [`compose-ghcr.yml`](compose-ghcr.yml) | **Production, recommended.** Run a pre-built release; no source or build toolchain on the host. | Pulled from GHCR |
| [`compose-build.yml`](compose-build.yml) | Production, but you want to build the image yourself from a checkout. | Built locally |
| [`compose-develop.yml`](compose-develop.yml) | Local development — live source mount + `uvicorn --reload`. | Built locally |

Both production files put nice4iot behind a reverse proxy: nice4iot is never
published itself; it joins an external `proxy` Docker network and only
`expose`s port 8080 to it, so a reverse proxy (Caddy, Traefik, nginx, …) on the
same network is the sole public entry point.

## Production from the pre-built image (recommended)

`.github/workflows/release.yml` builds the image and pushes it to
`ghcr.io/clausgf/nice4iot` on every `v*` tag (see *Releasing* below). The host
then only needs Docker and the one compose file — no checkout, git, or build:

```bash
mkdir -p data          # once, owned by your user — see the permissions note below
docker compose -f compose-ghcr.yml pull
docker compose -f compose-ghcr.yml up -d
```

To update later, `pull` again and `up -d` — run by hand, or from a cron /
systemd timer for automatic deployment of new releases. The file defaults to
`:latest`; pin `:0.13.0` instead for controlled, reviewable upgrades. For fully
hands-off updates, uncomment the bundled **Watchtower** service (it polls GHCR
and restarts on every new image — i.e. deploys releases unreviewed).

The GHCR image ships with the epaper extension baked in.

## Production, building the image yourself

Use [`compose-build.yml`](compose-build.yml); the build context is the
repository root (`context: ..`):

```bash
mkdir -p data
docker compose -f compose-build.yml up -d --build
```

**Deploying from your own directory** (e.g. next to your other services'
compose files) is usually cleaner than running from inside the checkout. Copy
`compose-build.yml` into that directory and point `build.context` at your
cloned nice4iot repo — an absolute path, since it is no longer `..`:

```yaml
    build:
      context: /home/you/git/nice4iot        # path to the cloned repo
      dockerfile: deploy/Dockerfile
```

Then `mkdir -p data` there and `docker compose -f compose-build.yml up -d
--build`; `git pull` in the repo and rebuild to update. (The `compose-ghcr.yml`
route above avoids this rebuild-on-the-host step entirely.)

## Local development

[`compose-develop.yml`](compose-develop.yml) builds the image for its
dependency environment, bind-mounts the host `app/` over it, and runs
`uvicorn --reload`, so code edits reload the running app live. It publishes the
app directly on `localhost:8080` — no reverse proxy, no `proxy` network:

```bash
mkdir -p data
docker compose -f compose-develop.yml up --build      # then open http://localhost:8080
```

It uses debug logging and a placeholder session secret — never expose it.

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

- **Admin UI** (the NiceGUI pages, under `/ui`) — for humans; guarded by
  `AUTH_PROVIDER` (off by default), which you must turn on before exposing it.
- **Device API** (`/api/*`) — for devices; already authenticated by per-device
  **bearer tokens**. It needs no extra network auth, only TLS.

The trap: if you protect the UI with a *blanket* proxy auth (e.g. oauth2-proxy in
front of the whole app), it will also block `/api/*` and lock out every device.
Because the UI lives under `/ui`, gating is a clean prefix rule: **require the
human login only for `/ui/*`**, and leave `/api/*` (device tokens), the NiceGUI
assets/WebSocket (`/_nicegui*`, `/_nicegui_ws`) and `/health` open. Everything
under `/ui` needs the login; `/ui/login` itself must stay reachable when you use
the built-in password provider. (`/` just redirects to `/ui`.)

## Configuration

Every setting is an environment variable — **full reference:
[docs/configuration.md](../docs/configuration.md)**. Set any of them under
`environment:` in your compose file. The deployment-specific knobs:

- **`NICEGUI_STORAGE_SECRET`** — long random value so UI sessions survive
  restarts. The compose files ship a placeholder; change it.
- **`PUID` / `PGID`** (build args) — the uid/gid the container runs as. Match the
  owner of the host `./data` directory. Build-time only, so they apply to
  `compose-build.yml` / `compose-develop.yml`; the pre-built GHCR image is built
  with `1000:1000`.
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
  `command:` line in your compose file, so NiceGUI emits `/iot`-prefixed asset,
  redirect, and WebSocket URLs.

## Releasing (building and publishing the image)

[`.github/workflows/release.yml`](../.github/workflows/release.yml) builds the
image and pushes it to `ghcr.io/clausgf/nice4iot` whenever a `v*` tag is pushed.
Tag a green `main` commit:

```bash
git tag v0.13.0 && git push --tags
```

The image is tagged with the full version (`0.13.0`), the major.minor (`0.13`),
and `latest`, and always includes the epaper extension. `compose-ghcr.yml` then
pulls it. Pushing to `ghcr.io/<owner>/…` uses the workflow's built-in
`GITHUB_TOKEN` (`packages: write`); no extra secret is needed. Make the package
public once in the repo's *Packages* settings so hosts can pull without a login.

## The epaper extension

`compose-build.yml` and `compose-develop.yml` build with
`INSTALL_EXTRAS="--extra epaper"` **by default**, and the pre-built GHCR image
ships with it baked in. It pulls in
[`nicepaper`](https://github.com/clausgf/nicepaper) (a public `git+https`
dependency — no credentials). Comment that build arg out to build without it.
Once installed the extension (`extensions.epaper`) auto-registers; enable it per
project under **Project → General → Extensions**.

## Notes

- **Healthcheck:** the image ships a `HEALTHCHECK` that polls `/health` inside the
  container, so `docker ps` shows healthy/unhealthy and Compose can restart on
  failure or gate `depends_on: { condition: service_healthy }`. It runs directly
  against the app, so it is independent of the reverse proxy and `--root-path`.
- **MQTT** is **off by default** (`MQTT_ENABLED=false`). If you enable it but the
  broker isn't reachable yet, the log shows `MQTT connection error … retrying`
  until it comes up — that is expected, not a failure of nice4iot.
- The image bakes `app/` in and installs the project, so `/docs` reports the real
  version. Rebuild the image to ship code changes, or use `compose-develop.yml`
  (live source mount + `uvicorn --reload`) for development — see *Local
  development* above. You can also run from source directly with
  `uv run uvicorn app.main:app --reload` (see the top-level README).
- **About / Software Bill of Materials:** the user menu → **About** (`/about`)
  shows nice4iot's version and build commit, the niceview and epaper/nicepaper
  versions, and every installed package with its version. The GHCR image bakes
  the release commit in (`NICE4IOT_GIT_COMMIT`); locally-built images show the
  version only.
- These compose files are examples; validate the build in your own environment.
