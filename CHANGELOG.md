# Changelog

All notable changes to this project are documented here. Per `CLAUDE.md`, every
API change must be recorded. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [0.17.0] - 2026-08-03

### Added

- **Firmware version in the telemetry body.** `POST /api/telemetry` now recognises
  the reserved string keys `firmware_version` and `firmware_commit` as device
  metadata (removed before numeric processing) and routes them to the same runtime
  state as the `X-Firmware-*` headers — so a device may report its version in the
  telemetry body instead of via a header. Body wins if both are present.

## [0.16.1] - 2026-08-03

### Changed

- **Firmware source card moved to the General tab.** It is now a foldable
  configuration card (matching Forwarding/Telemetry/Logging/Files) instead of
  living on the Files tab, shows the resolved GitHub Releases URL as a link, and
  no longer renders the internal `updated_at` timestamp.

## [0.16.0] - 2026-08-03

### Added

- **Firmware pull from GitHub Releases.** The project/device **Files** tab gains a
  **Firmware source** card: point a project (or device) at a *public* GitHub repo
  and pull a release asset (default `firmware.bin`) into that directory —
  manually (*Pull now*) or automatically (opt-in per-source background loop with a
  configurable interval, 5-minute floor, conditional ETag polling). Channels:
  `stable` / `prerelease` / `pinned` tag. The download is streamed with a 64 MiB
  cap and, when GitHub supplies the asset `digest`, SHA-256-verified before an
  atomic write; state is recorded in `.firmware.state.json`. No credentials are
  ever sent (public repos only); `repo` is `owner/name` (no URLs → no SSRF).
  Optional MQTT force-publish on pull for device-level sources. The device API is
  unchanged — devices keep fetching the file via `GET /api/file`. See
  [docs/firmware-releases.md](docs/firmware-releases.md).

## [0.15.1] - 2026-08-03

### Added

- **Build identity on `/health`.** `GET /health` now returns `version`, `commit`,
  and `commit_date` alongside `status` — for deployment verification and
  monitoring. The About page also shows the commit date next to the commit, and
  the GHCR image bakes it in via `NICE4IOT_GIT_COMMIT_DATE`.

### Changed

- **Deploy:** the bundled (commented) Watchtower service now uses the maintained
  `ghcr.io/nicholas-fedor/watchtower` fork; the original `containrrr/watchtower`
  is unmaintained and a modern Docker daemon rejects its old client ("client
  version 1.25 is too old").

### Fixed

- **Telemetry read/write now follow HTTP redirects.** A Prometheus/VictoriaMetrics
  endpoint behind a proxy that 308-redirects (e.g. http→https or trailing-slash
  normalisation) caused reads to fall back to the local store and writes to be
  silently dropped (308 < 400 read as success). Both paths now use
  `follow_redirects=True` (307/308 preserve method and body).

## [0.15.0] - 2026-08-02

### Added

- **Device firmware-version reporting.** A device may report its running firmware
  via the optional `X-Firmware-Version` (and optional `X-Firmware-Commit`)
  request header on any authenticated device API call, and at `POST /api/provision`.
  The value is stored server-side in a per-device `.runtime.json` sidecar (next to
  `last_seen_at`, never in `device.json`) and shown in the **Device → Dashboard**
  Status card and the **Project → Devices** table. Headers are optional and
  backward-compatible; omitting them leaves the last reported value unchanged. See
  [docs/firmware-releases.md](docs/firmware-releases.md#reporting-the-running-version).

### Changed

- Per-device `last_seen_at` now lives in `.runtime.json` (was the bare-timestamp
  `.last_seen` file), alongside the reported firmware fields. Existing `.last_seen`
  files are still read as a migration fallback.
- The device-log append hot path (`POST /api/log`) and the UI file-upload write are
  now off-loaded to a worker thread (`anyio.to_thread`), matching the telemetry hot
  path and `PUT /api/file`.
- Dependency lock: **niceview** pin moved to the relocated `0.10.0` tag (mypy typing
  fix in `DirectoryAdapter`).

### Fixed

- **UI file upload** was broken since the NiceGUI 3.x upgrade (`UploadEventArguments`
  no longer exposes `.name`/`.content`); it now uses `e.file.name` /
  `await e.file.read()`. Regression shipped in 0.14.0.

## [0.14.0] - 2026-08-01

### Added

- **File editing in the UI.** The project/device **Files** tab is now a file
  browser with a list ↔ detail **drill-down** (built on niceview's
  `DrillDownWrapper`): JSON and recognised text files open in an inline editor,
  images (png/jpg/gif/webp ≤ 2 MB) in an inline preview; SVG and other binaries
  stay download-only.
- **JSON forms.** A flat JSON object also offers a **Form** tab with widgets
  inferred from its values (raw stays default). With a sibling
  `<name>.schema.json` (a minimal JSON-Schema subset — types, `enum`→select,
  `date`, multiline, `minimum`/`maximum`, `maxLength`, `required`,
  `title`/`description`), the schema-driven form becomes the default. Saving
  **merges** into the file, preserving keys the schema/form does not cover.
- **Device-schema approval.** A schema uploaded by a device is inert until a user
  approves it; approval is bound to the schema's content hash, so a device
  changing the schema forces re-approval. Editing a schema in the UI approves it
  automatically (admin provenance). Untrusted schemas are rendered by a small
  dedicated interpreter — never `pydantic.create_model`/niceview, never as
  HTML/Markdown — and `$ref`/`pattern` are not honoured (no SSRF / ReDoS). See
  [docs/file-forms.md](docs/file-forms.md).

### Changed

- Updated dependencies: **niceview 0.9.1 → 0.10.0** (fixes `ui.number` conversion
  so a cleared numeric field becomes `None` again — a stale model-validator error
  such as the epaper widget's "Set width and height together …" now clears; adds
  the `DirectoryAdapter` all-files mode the file browser builds on) and
  **nicepaper 0.13.0 → 0.13.1**.

## [0.13.1] - 2026-07-24

### Changed

- Refreshed all dependencies. Notably **niceview 0.9.0 → 0.9.1**, which fixes
  `ui.number` conversion so a cleared numeric field becomes `None` again — a
  stale model-validator error (e.g. the epaper widget's "Set width and height
  together …") now clears once both fields are emptied. Also **nicepaper
  0.12.0 → 0.13.0** (weather backoff/outage visibility, English defaults),
  **NiceGUI 3.14.0 → 3.15.0**, **FastAPI 0.139.2 → 0.140.0**, **ruff → 0.16.0**,
  and assorted patch bumps. The `/ui` routing was re-verified end to end against
  NiceGUI 3.15.0.
- `deploy/compose-ghcr.yml` now simply tracks `:latest` (the version-pinned
  example line was dropped to avoid per-release churn; pinning is still
  documented as an option).

## [0.13.0] - 2026-07-24

### Added

- **Preferences page** (user menu → Preferences, `/ui/preferences`): the global
  MQTT broker status and any extension-registered global cards now live here, so
  `/ui` is a clean list of projects only.
- The About page (`/ui/about`) lists nice4iot's own version and build commit
  first, before niceview and the epaper extension. The GHCR image bakes the
  release commit in via `NICE4IOT_GIT_COMMIT`; source/dev runs read it from git
  (with a `-dirty` marker for uncommitted changes).

### Changed

- **The UI now lives under `/ui`** (`/` redirects there); `/api/*` is unchanged.
  Projects are at `/ui/project/{project}`, devices at
  `/ui/project/{project}/device/{device}`, and About/login moved under `/ui`
  too. The literal `/ui/project/` prefix removes the top-level namespace
  collisions of the old flat scheme — a project can no longer be confused with a
  reserved page, so e.g. a project literally named `about` now works, and the
  0.12.0 `/sbom` → *Project "sbom" does not exist* bug is structurally gone.
  **Breaking** for UI bookmarks; **devices are unaffected** (`/api/*` unchanged).
  Reverse proxies now gate the human UI with a single prefix rule (`/ui/*`); see
  deploy/README.md.
- Renamed the user-menu entry "Software Bill of Materials" to **About**.

## [0.12.0] - 2026-07-24

### Added

- **Software Bill of Materials** page in the user menu (`/sbom`): lists every
  installed Python package and its version, with the niceview and epaper
  (nicepaper) versions highlighted at the top.
- **GHCR release pipeline** — `.github/workflows/release.yml` builds the image
  and pushes it to `ghcr.io/clausgf/nice4iot` (tags `<version>`, `<major.minor>`,
  `latest`, epaper included) on every `v*` git tag.
- **`deploy/compose-ghcr.yml`** — run the pre-built GHCR image (no source/build
  on the host); pull-based updates by default, with a commented-out Watchtower
  service for hands-off auto-updates.
- **`deploy/compose-develop.yml`** — local development: builds the image, mounts
  the host `app/` over it, and runs `uvicorn --reload` on `localhost:8080`.

### Changed

- Renamed `deploy/docker-compose.yml` to **`deploy/compose-build.yml`** (the
  build-from-source production variant) now that there are three compose files.

## [0.11.3] - 2026-07-23

### Changed

- Updated the optional `epaper` extension dependency (nicepaper) from 0.11.0 to
  0.12.0: adds an Image widget. Pinned by commit in `uv.lock`; only affects
  images built with `--extra epaper`.
- On the device **General** tab, the Danger Zone card is now rendered last,
  after any extension-registered cards, matching the project page.

### Fixed

- The device Status card no longer shows two stacked separators when a device
  has neither a location nor a description: the separator above that block is
  now only drawn when the block has content.

## [0.11.2] - 2026-07-23

### Changed

- Updated the optional `epaper` extension dependency (nicepaper) from 0.10.0 to
  0.11.0: WeatherChart axis titles and per-aspect font override. Pinned by commit
  in `uv.lock`; only affects images built with `--extra epaper`.

### Fixed

- On the device **General** tab, extension-registered cards (e.g. E-Paper) now
  use the same `subtitle1` header size as the built-in expansions on that tab.
  They were falling through to `config_expansion`'s `h6` default (correct on the
  project page, too large next to the device page's `subtitle1` headers).

## [0.11.1] - 2026-07-22

### Changed

- Updated the optional `epaper` extension dependency (nicepaper) from 0.9.0 to
  0.10.0: WeatherNow wind-chart metric, localized text and configurable
  wind-speed unit, and schedule size validation/warnings. Pinned by commit in
  `uv.lock`; only affects images built with `--extra epaper`.

### Fixed

- The `/api/*` namespace now always answers with JSON. NiceGUI's `ui.run_with`
  mounts the UI as a catch-all at `/`, so any unmatched request under `/api/*` —
  an unknown path, or a wrong HTTP method on a known endpoint (e.g. `GET`ting the
  `POST`-only `/api/provision`) — fell through to the UI and returned an HTML
  page instead of a JSON error. A guard route registered after the API routers
  (which still win on an exact method+path match) now returns a JSON `404`.
  Correct device calls were unaffected; this only corrects the error responses.
  Regression-tested in `tests/test_api_namespace.py` — the existing suite missed
  it because its fixtures build a router-only app without NiceGUI mounted.

## [0.11.0] - 2026-07-22

### Added

- Container `HEALTHCHECK` polling `/health`, so `docker ps` reports healthy/
  unhealthy and Compose can restart on failure or gate `depends_on`. Runs
  directly against the app (independent of the reverse proxy / `--root-path`).
- Heuristic OpenMetrics UNIT metadata for the Prometheus backend: a recognised
  unit suffix (`_celsius`, `_bytes`, `_seconds`, …) fills the metric's unit.
  Additive — backends that ignore it (e.g. VictoriaMetrics) are unaffected.
- Documented VictoriaLogs as a supported log backend via the Loki push API
  (`…/insert/loki/api/v1/push?_stream_fields=project,device`) — no code, the
  existing Loki backend already speaks it, mirroring VictoriaMetrics.

### Changed

- **InfluxDB line-protocol data model** now mirrors the Prometheus backend:
  measurement is `<project>`, `kind` is a **tag** (was part of the measurement),
  and the redundant `project` tag is gone —
  `weatherstation,device=…,kind=sensors temperature=22.4`. **Breaking** for
  existing InfluxDB dashboards/queries built on the old `…_<kind>` measurement.
- The browser tab title is now `nice4iot` (was the framework default `NiceGUI`).

### Fixed

- Switching from dark back to light mode required a page refresh; both toggles
  now drive a single `ui.dark_mode()` instance and apply immediately.

## [0.10.0] - 2026-07-22

### Added

- `CORS_ALLOW_ORIGINS` environment variable controls which browser origins may
  call the REST API (default `["*"]`). A wildcard origin no longer advertises
  credentials, per the CORS spec. See docs/configuration.md.
- `MQTT_ENABLED` / `MQTT_SERVER` / `MQTT_PORT` / `MQTT_USERNAME` /
  `MQTT_PASSWORD` / `MQTT_CLIENT_ID` environment variables configure the global
  MQTT broker connection (see Changed).
- `DEFAULT_TELEMETRY_*` and `DEFAULT_LOGGING_LOKI_*` environment variables seed a
  new project's telemetry and logging config at creation time (Prometheus and
  InfluxDB backends, and Loki), so projects sharing one backend need no manual
  per-project setup. All values stay editable per project; unset = model default.
- `DEVICE_TOKEN_EXPIRES_IN` seeds a new project's device-token lifetime, and the
  previously-unused `DEVICE_TOKEN_LENGTH` now seeds `Project.device_token_length`.
  See docs/configuration.md.
- `mount_extension_router()` gained a `require_device_auth` keyword: when set,
  every route on the extension router requires a valid device bearer token
  (validated by the shared `device_auth` dependency, 401 otherwise), the same
  contract as the built-in device endpoints. It requires each route to carry a
  `device_name` path parameter and fails loudly at mount time otherwise. The
  default is `False` (enablement-gate only, unchanged). See docs/extensions.md.

### Changed

- The global MQTT broker connection is now configured through the `MQTT_*`
  environment variables instead of the UI, and is **disabled by default**
  (previously enabled, connecting to `localhost:1883`). The `.mqtt.json` file
  and its UI editor are gone; the Projects page shows the connection status
  read-only. This keeps the broker password out of the data volume. Per-project
  MQTT enablement is unchanged.

### Removed

- The `app.mqtt.models.MqttGlobalConfig` model and the global MQTT settings UI
  card, superseded by the `MQTT_*` environment variables above.

### Fixed

- Corrected the `POST /api/provision` 400-response description in the OpenAPI
  docs: project and device names must match `[a-zA-Z_][a-zA-Z0-9_]*` (letters,
  digits and underscore, no leading digit), not the `-`/`+` the text previously
  claimed. Only the documentation was wrong; validation was already stricter.
- Corrected the `Project.is_active` / `Device.is_active` field descriptions:
  an inactive project or device is rejected with **403 only on
  `POST /api/provision`**. On the device data endpoints (telemetry, log, file,
  forward) all auth failures — including inactive/disabled — are normalised to
  **401**, so the earlier "403 on all API calls" wording was wrong. Behaviour is
  unchanged; only the docs were corrected.

_0.9.0 was the first release; pre-release history is in the git log._
