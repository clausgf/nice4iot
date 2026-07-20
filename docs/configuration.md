# Configuration

Environment variables and management-UI authentication.

[← Documentation index](README.md) · [Project README](../README.md)

---

## Configuration

Settings are read from environment variables (or a `.env` file):

| Variable | Default | Description |
|---|---|---|
| `PROJECTS_DIR` | `data/projects` | Root directory for all project and device data |
| `PROVISIONING_TOKEN_LENGTH` | `64` | Length of generated provisioning tokens |
| `PROVISIONING_TOKEN_EXPIRES_IN` | `365d` | Lifetime of provisioning tokens |
| `DEVICE_TOKEN_LENGTH` | `32` | Length of generated device tokens |
| `MAX_FILE_UPLOAD_SIZE` | `10485760` | Maximum file upload size in bytes (10 MiB) |
| `MAX_TELEMETRY_SIZE` | `8192` | Maximum telemetry body size in bytes (8 KiB) |
| `MAX_LOG_SIZE` | `8192` | Maximum log body size in bytes (8 KiB) |
| `TIMEZONE` | `Europe/Berlin` | Server timezone (for log timestamps) |
| `NICEGUI_STORAGE_SECRET` | `""` | Secret for NiceGUI session storage |
| `AUTH_PROVIDER` | `none` | Admin UI auth: `none`, `proxy` (reverse-proxy-forwarded identity), or `password` (built-in login, htpasswd) |
| `AUTH_USER_HEADERS` | see below | `proxy` provider: header names carrying the forwarded username, first non-empty wins |
| `AUTH_LOGOUT_URL` | `null` | `proxy` provider: logout link shown in the user menu (e.g. `/oauth2/sign_out`); unset hides it |
| `AUTH_HTPASSWD_FILE` | `data/htpasswd` | `password` provider: bcrypt htpasswd file, manage with `htpasswd -B` |

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
