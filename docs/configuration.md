# Configuration

Environment variables and management-UI authentication.

[← Documentation index](README.md) · [Project README](../README.md)

---

Settings are read from environment variables (or a `.env` file):

| Variable | Default | Description |
|---|---|---|
| `PROJECTS_DIR` | `data/projects` | Root directory for all project and device data. In the container keep the default — it maps to the mounted `data` volume; change only together with the volume mount |
| `PROVISIONING_TOKEN_LENGTH` | `64` | Length of generated provisioning tokens |
| `PROVISIONING_TOKEN_EXPIRES_IN` | `365d` | Lifetime of provisioning tokens |
| `DEVICE_TOKEN_LENGTH` | `32` | Length of device tokens; also seeds a new project's editable `device_token_length` |
| `DEVICE_TOKEN_EXPIRES_IN` | `7` | Default device-token lifetime in days; seeds a new project's editable setting |
| `MAX_FILE_UPLOAD_SIZE` | `10485760` | Maximum file upload size in bytes (10 MiB) |
| `MAX_TELEMETRY_SIZE` | `8192` | Maximum telemetry body size in bytes (8 KiB) |
| `MAX_LOG_SIZE` | `8192` | Maximum log body size in bytes (8 KiB) |
| `TIMEZONE` | `Europe/Berlin` | Server timezone (for log timestamps) |
| `NICEGUI_STORAGE_SECRET` | `""` | Signs the NiceGUI session cookie. Set a long random value so admin-UI login sessions survive restarts and cookies can't be forged; empty means sessions reset on every restart |
| `CORS_ALLOW_ORIGINS` | `["*"]` | JSON list of browser origins allowed to call the REST API — see [CORS](#cors) below |
| `MQTT_ENABLED` | `false` | Master switch for the shared MQTT broker connection; no connection is attempted unless `true` |
| `MQTT_SERVER` | `localhost` | Broker hostname or IP |
| `MQTT_PORT` | `1883` | Broker port (TLS typically `8883`) |
| `MQTT_USERNAME` | `""` | Login username; empty = anonymous |
| `MQTT_PASSWORD` | `""` | Login password |
| `MQTT_CLIENT_ID` | `nice4iot` | MQTT client ID; must be unique per broker |
| `AUTH_PROVIDER` | `none` | Admin UI auth: `none`, `proxy` (reverse-proxy-forwarded identity), or `password` (built-in login, htpasswd) |
| `AUTH_USER_HEADERS` | see below | `proxy` provider: header names carrying the forwarded username, first non-empty wins |
| `AUTH_LOGOUT_URL` | `null` | `proxy` provider: logout link shown in the user menu (e.g. `/oauth2/sign_out`); unset hides it |
| `AUTH_HTPASSWD_FILE` | `data/htpasswd` | `password` provider: bcrypt htpasswd file, manage with `htpasswd -B` |

Complex values (`CORS_ALLOW_ORIGINS`, `AUTH_USER_HEADERS`) are JSON — pass a JSON
array string, e.g. `CORS_ALLOW_ORIGINS='["https://app.example.com"]'`. Booleans
accept `true`/`false`/`1`/`0`.

## CORS

`CORS_ALLOW_ORIGINS` controls which **browser** origins may call the REST API
from JavaScript. It has no effect on devices — they are plain HTTP clients, not
browsers, and CORS is a browser-enforced mechanism. It only matters when a web
page hosted on a different origin calls the API.

Concrete example: a dashboard served from `https://dash.example.com` runs

```js
fetch("https://iot.example.com/api/...")
```

Because the page's origin (`dash.example.com`) differs from the API's
(`iot.example.com`), the browser first checks whether the API permits that
origin. With the default `["*"]` any origin is allowed. To lock it down:

```
CORS_ALLOW_ORIGINS=["https://dash.example.com"]
```

Now a page on any other origin receives no CORS headers and the browser blocks
it from reading the response. Once narrowed from `*`, credentialed requests
(cookies) are also permitted; with `*` they are not, because the CORS spec
forbids combining a wildcard origin with credentials.

## MQTT broker

The shared MQTT broker connection is configured entirely through the `MQTT_*`
variables in the table above and is **disabled by default**. There is no UI
editor — this keeps the password out of the data volume; prefer a Docker secret
over a plaintext value in compose. Per-project MQTT use is still toggled in the
project settings, and the global connection status is shown (read-only) on the
Projects page.

## Defaults for new projects

Telemetry and logging are configured **per project**, but when most projects
share one backend (a common VictoriaMetrics, a central Loki) the `DEFAULT_*`
variables seed each **new** project's config at creation time. Everything stays
editable per project in the UI afterwards — these only set the initial value.
Leaving a variable unset keeps the model default, so with none set behaviour is
exactly as before. Existing projects are never touched. Put passwords/tokens in
a secret.

| Variable | Seeds | Notes |
|---|---|---|
| `DEFAULT_TELEMETRY_BACKEND` | telemetry backend | `none` / `prometheus` / `influxdb` |
| `DEFAULT_TELEMETRY_PROMETHEUS_PUSH_URL` | Prometheus remote-write URL | e.g. `http://victoriametrics:8428/api/v1/write` |
| `DEFAULT_TELEMETRY_PROMETHEUS_PULL_URL` | Prometheus query URL | e.g. `http://victoriametrics:8428/api/v1/` |
| `DEFAULT_TELEMETRY_PROMETHEUS_USERNAME` / `_PASSWORD` | Basic-Auth | password is a secret |
| `DEFAULT_TELEMETRY_INFLUXDB_WRITE_URL` | InfluxDB line-protocol write URL | |
| `DEFAULT_TELEMETRY_INFLUXDB_DATABASE` / `_ORG` / `_BUCKET` | InfluxDB targeting | 1.x db, or 2.x org/bucket |
| `DEFAULT_TELEMETRY_INFLUXDB_USERNAME` / `_PASSWORD` / `_TOKEN` | InfluxDB auth | password/token are secrets |
| `DEFAULT_LOGGING_LOKI_ENABLED` | Loki backend on/off | |
| `DEFAULT_LOGGING_LOKI_URL` | Loki push URL | Grafana Loki or VictoriaLogs, e.g. `http://victorialogs:9428/insert/loki/api/v1/push?_stream_fields=project,device` |
| `DEFAULT_LOGGING_LOKI_USERNAME` / `_PASSWORD` / `_TENANT_ID` | Loki auth / multi-tenancy | password is a secret |

`DEVICE_TOKEN_LENGTH` and `DEVICE_TOKEN_EXPIRES_IN` (in the main table above)
likewise seed a new project's device-token settings.

## Command-line arguments

nice4iot runs under [uvicorn](https://www.uvicorn.org/settings/); a few
process- and transport-level options live on its command line rather than in the
environment. The two most relevant:

- **`--root-path /iot`** — the public path prefix when serving under a sub-path
  behind a reverse proxy; NiceGUI uses it to build asset, redirect, and
  WebSocket URLs. See [deploy/README.md](../deploy/README.md).
- **`--log-level info`** — log verbosity
  (`critical` / `error` / `warning` / `info` / `debug` / `trace`).

Set them in the compose `command:` (or your process manager):

```
uvicorn app.main:app --host 0.0.0.0 --port 8080 --root-path /iot --log-level info
```

See the [uvicorn settings docs](https://www.uvicorn.org/settings/) for the rest
(workers, TLS, proxy headers, …).

## Authentication

`AUTH_PROVIDER` selects how the UI authenticates users:

- `none` (default): no authentication (local development, or when
  access is already restricted at the network level).
- `proxy`: an authenticating reverse proxy in front of the app (e.g.
  Caddy with oauth2-proxy) handles the login; the app reads the
  forwarded identity from request headers.
  - `AUTH_USER_HEADERS`: JSON list of headers carrying the username
    (defaults match oauth2-proxy: `X-Forwarded-Preferred-Username`,
    `X-Forwarded-User`, `X-Forwarded-Email`); the first non-empty
    value is shown in the UI.
  - `AUTH_LOGOUT_URL`: logout link shown in the user menu, e.g.
    `/oauth2/sign_out`; unset hides the entry.
  - The headers are only trustworthy when the app is reachable
    exclusively through the proxy.
  - Deployment note (Caddy + oauth2-proxy): oauth2-proxy must be told
    to expose the identity (`--set-xauthrequest`, and/or
    `--pass-user-headers` when proxying through oauth2-proxy itself)
    and Caddy's `forward_auth` block must forward it to the app, e.g.

    ```
    forward_auth oauth2-proxy:4180 {
        uri /oauth2/auth
        copy_headers X-Auth-Request-Preferred-Username>X-Forwarded-Preferred-Username X-Auth-Request-User>X-Forwarded-User X-Auth-Request-Email>X-Forwarded-Email
    }
    ```

    Set `AUTH_LOGOUT_URL=/oauth2/sign_out` for a working logout entry.
    After deploying, check once which of the configured headers
    actually arrives and adjust `AUTH_USER_HEADERS` if needed.
- `password`: built-in login page. Users live in an htpasswd file with
  bcrypt hashes (`AUTH_HTPASSWD_FILE`, default `data/htpasswd`),
  maintained with the standard Apache tool:

  ```
  htpasswd -c -B data/htpasswd alice   # create file and first user
  htpasswd -B data/htpasswd bob        # add/update further users
  ```

  Only bcrypt entries (`-B`) are accepted; the file is re-read on each
  login attempt, so changes apply without a restart. Set a strong
  `NICEGUI_STORAGE_SECRET`, since it signs the session cookie.
