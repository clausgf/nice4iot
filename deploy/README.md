# Deployment

A container image ([`Dockerfile`](Dockerfile)), three Docker Compose files —
each for a different way of running nice4iot — and an example
[`Caddyfile`](Caddyfile) for the reverse proxy in front of it. Run the commands
below from this `deploy/` directory.

| File | Use it when | Image |
|---|---|---|
| [`compose-ghcr.yml`](compose-ghcr.yml) | **Production, recommended.** Run a pre-built release; no source or build toolchain on the host. | Pulled from GHCR |
| [`compose-build.yml`](compose-build.yml) | Production, but you want to build the image yourself from a checkout. | Built locally |
| [`compose-develop.yml`](compose-develop.yml) | Local development — live source mount + `uvicorn --reload`. | Built locally |

Both production files put nice4iot behind a reverse proxy: nice4iot is never
published itself; it joins an external `proxy` Docker network and only
`expose`s port 8080 to it, so a reverse proxy (Caddy, Traefik, nginx, …) on the
same network is the sole public entry point. The proxy is deliberately not part
of these files — you usually already run one. [`Caddyfile`](Caddyfile) is a
copy-ready example of the nice4iot side of that config.

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
systemd timer for automatic deployment of new releases. The file tracks
`:latest`; to pin a specific release for controlled, reviewable upgrades,
replace `latest` with a version tag (e.g. `:0.13.0`). For fully hands-off
updates, uncomment the bundled **Watchtower** service (it polls GHCR and
restarts on every new image — i.e. deploys releases unreviewed). It uses the
actively-maintained `ghcr.io/nicholas-fedor/watchtower` fork; the original
`containrrr/watchtower` is unmaintained and a modern Docker daemon rejects its
old client ("client version 1.25 is too old").

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

## Serving display images over plain HTTP

E-paper displays are not browsers: firmware polling `image.png` usually has no
certificate store worth the name, so an HTTPS-only deployment can be
unreachable for the very devices the images exist for. The supported answer is
a second, plain-HTTP listener **in the reverse proxy** that serves nothing but
the image endpoint, restricted to the LAN the displays are on — not a second
listener inside nice4iot, which would duplicate what the proxy already does
well. [`Caddyfile`](Caddyfile) ships both listeners; the relevant half:

```caddyfile
# plain HTTP for the displays: images only, LAN only
http://:8081 {
	@image {
		remote_ip 192.168.2.0/24
		path_regexp ^/api/ext/epaper/[^/]+/screens/[^/]+/image\.png$
	}
	handle @image {
		reverse_proxy nice4iot:8080
	}
	respond 404
}
```

Adapt `192.168.2.0/24` to your display network. Both conditions are ANDed, and
everything else on that port — the admin UI, the rest of the API, requests from
outside the LAN — gets a flat `404`. The path pattern matches the epaper
extension's route, `/api/ext/epaper/<project>/screens/<screen>/image.png`.
`path_regexp` sees the path as this listener receives it, so the sub-path
scenario above does not apply here: point the displays at the bare
`http://<host>:8081/api/ext/epaper/…` path, without the `/iot` prefix.

Two Docker-specific points, since the proxy here runs in a container:

- **Publish the port on the proxy, not on nice4iot.** Add `"8081:8081"` to the
  proxy service's `ports:` — nice4iot itself stays unpublished, exactly as
  before. Bind it to the LAN interface (`"192.168.2.10:8081:8081"`) if the host
  also has a public address.
- **`remote_ip` needs the real client address.** Docker's iptables DNAT
  preserves the source IP for connections arriving from the LAN, so the matcher
  works; but if the proxy sits behind *another* hop, `remote_ip` matches that
  hop instead. Verify with a request from a display subnet before trusting it.

This **adds** a way to reach the images, it does not move them: `image.png`
stays available over HTTPS as well, subject to whatever protects it there. That
is intended — the screen editor loads its preview from its own origin with a
relative URL, so excluding the image path from the HTTPS site to "have only one
way in" breaks the preview.

What this does and does not buy you (see nicepaper's
[SECURITY.md](https://github.com/clausgf/nicepaper/blob/main/SECURITY.md) for
the full discussion):

- **Not confidentiality.** The images travel unencrypted and unauthenticated;
  anyone on that LAN can fetch any screen of any project. Fine for a weather
  panel, a deliberate decision for a room calendar whose rendered image shows
  meeting subjects and organisers.
- **`remote_ip` is not authentication.** It matches the directly connecting
  peer, which anything on the same LAN can hold. It keeps the plain port off
  the internet; it does not keep a compromised device off it.
- **The editor views come along.** `?raw=true` and `?boxes=true` live on the
  same path. Add `not query raw=*` and `not query boxes=*` to the matcher if
  that bothers you.
- **Device tokens are unaffected.** The epaper image route is mounted without
  `require_device_auth`, so it needs no bearer token either way; the rest of
  `/api` keeps its token auth, and none of it is reachable on port 8081.

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
project under **Project → General → Extensions**. If your displays can't do
TLS, see *Serving display images over plain HTTP* above.

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
