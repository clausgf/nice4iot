# Changelog

All notable changes to this project are documented here. Per `CLAUDE.md`, every
API change must be recorded. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

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
