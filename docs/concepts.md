# Core Concepts

The domain model: how state is stored, how devices authenticate, how files and firmware reach a device, and how telemetry, alarms and health tracking work.

[← Documentation index](README.md) · [Project README](../README.md)

---

## Data Storage

All state is stored on the filesystem under `data/projects/` (configurable via `PROJECTS_DIR` env var):

```
data/projects/
└── <project_name>/
    ├── .project.json           # Project settings (autosave)
    ├── .provisioning.json      # Provisioning token list
    ├── .telemetry.json         # Telemetry backend config
    ├── .logging.json           # Logging backend config
    ├── .forwards.json          # Named HTTP forwarding rules
    ├── .firmware.json          # Firmware source (GitHub/GitLab repo) for project-wide firmware.bin
    ├── .firmware.state.json    # Last firmware pull: tag, digest, pulled_at, etag
    ├── .seed.json              # Seed data for a fresh device: WiFi, API URL, TLS trust
    ├── <shared_file>           # Project-wide fallback files served to devices
    └── <device_name>/
        ├── .device.json        # Device settings (autosave, optimistic-locked)
        ├── .firmware.json          # Optional per-device firmware source (overrides project)
        ├── .firmware.state.json    # Last firmware pull for this device
        ├── .seed_override.json # Optional per-device WiFi override of the project's Seed settings
        ├── .runtime.json       # device-reported runtime state: last_seen_at (written on
        │                       # every API auth) + firmware_version/commit (reported via
        │                       # X-Firmware-* headers) + system_metrics/system_labels/
        │                       # system_reported_at (snapshot of the last kind='system'
        │                       # telemetry push: battery_V, wifi_rssi, firmware_* labels).
        │                       # Kept separate so device.json is only written on explicit
        │                       # user/provisioning actions (avoids lock conflict)
        ├── .tokens.json        # Device bearer token list (file-locked on write)
        ├── .device.log         # File logging backend output (rotated)
        ├── .device_metrics.jsonl  # Local telemetry ring buffer (max 2 000 lines)
        ├── .data_view.json     # Persisted Data-tab explorer config (window + traces)
        └── <device_file>       # Device-specific files (override project defaults)
```

Project and device names double as directory names and as the telemetry metric-name prefix, so they must be valid identifiers: `[a-zA-Z_][a-zA-Z0-9_]*` (letters, digits and underscore only, no leading digit, no `-`/`+`). This guarantees a valid Prometheus metric name `<project>_<field>` and needs no backend-specific escaping. Path traversal is prevented by resolving and checking all paths against their expected base directory.

> **Upgrading:** earlier versions allowed `-` and `+` in names. A project or device directory whose name violates the rule above is no longer listed or accessible — rename it on disk (e.g. `my-proj` → `my_proj`) before upgrading.

All writes use a write-to-temp-then-rename pattern to avoid partial writes.

## Two-Tier Token Model

1. **Provisioning tokens** — long-lived (default: 1 year), scoped to a project. Created in the UI and flashed into device firmware.
2. **Device tokens** — short-lived (default: 7 days), scoped to a device. Issued by `POST /api/provision` in exchange for a valid provisioning token.

On provisioning, the platform can optionally auto-create the device record (`is_autocreate_devices`) and auto-approve it (`is_provisioning_autoapproval`), or require explicit operator approval first.

Each device may hold at most **32 active tokens** simultaneously. When the cap is reached, the token with the oldest `last_use_at` is evicted before the new one is stored.

On each successful provisioning the device also records **which provisioning token it used**: a short, non-reversible fingerprint of the token (`last_provisioning_token_fingerprint`) plus the token's expiry (`last_provisioning_token_expires_at`). The shared secret itself is never copied onto the device. Because the expiry travels with the device record, *"which devices are affected by a token expiring soon"* is answerable by filtering devices directly — even after the token is removed from `.provisioning.json`. Each `AuthToken` carries the same derived `fingerprint` (recomputed from its value on every change), so a device's recorded fingerprint can be matched back to a concrete provisioning token.

## Seed Data

`.seed.json` holds the bootstrap data an arduino4iot device needs before it can call `POST /api/provision` and that nice4iot has no other source for: WiFi SSID/password, the server's public API URL, and — for a self-hosted/self-signed TLS setup — the CA certificate to trust. Combined with the project name and a provisioning token (above), this is what gets flashed or copied onto a fresh device. nice4iot cannot infer the API URL itself: it has no `base_url` setting and normally sits behind a reverse proxy that terminates TLS in front of it.

A device's `.seed_override.json` optionally replaces just the WiFi SSID/password for that one device (`override_enabled`); the API URL and TLS settings always come from the project, since they don't vary per device.

### Getting the seed onto a device

The project Devices tab (and each device's own Seed card) offer three ways to
get a device from "just created" to "actually seeded", all starting from the
same device record (`app.core.device.ui.prompt_create_device`) — the operator
picks a name, the device authenticates as itself once it reports one (see
"Device Lifecycle" below):

1. **New** — just the device record; seeded some other way (build-time `-D`
   defines, a manual `nvs_partition_gen.py` run, ...). Unchanged status quo.
2. **Flash Device** (`app.core.seed.action_dialogs.web_serial_flash_dialog`) —
   flashes esp32paper's pre-merged full-flash image for the chosen board
   (`merged-<board>.bin`: bootloader + partition table + boot_app0 + app,
   merged by esp32paper's own CI at the real offsets its build used) plus a
   freshly generated NVS image (`app.core.seed.nvs`, shelling out to
   `esp-idf-nvs-partition-gen` rather than reimplementing ESP-IDF's NVS
   binary format), over Web Serial via a vendored
   [ESP Web Tools](https://github.com/esphome/esp-web-tools)
   `<esp-web-install-button>` (`app/static/esp-web-tools/`). Works on a blank
   board — no prior flash needed. The NVS offset/size are parsed
   (`app.core.seed.partition_table.find_partition`) from that same build's
   published `partitions-<board>.csv`, never hardcoded — `app.core.seed.boards`
   only holds each board's chip family and its release-asset naming, on
   purpose (see that module's docstring for why offsets used to live there
   and don't anymore).
3. **AP + Form Setup** (`app.core.seed.action_dialogs.ap_qr_dialog`) — shows
   the explanation, a QR code, and the setup URL for arduino4iot's own
   SoftAP + captive-portal form (see "First-time provisioning" below); the
   form itself runs entirely on the device. Printable.

Both 2 and 3 resolve the device's *effective* seed — the project's Seed
settings with that device's WiFi override applied — against an
operator-picked provisioning token (`app.core.seed.backend.get_effective_seed`).

## Device Lifecycle

```
Provisioning request (provisioning token)
  → device created (if autocreate) or looked up
  → approval checked
  → device token issued (old expired tokens purged, cap enforced)
  → provisioning-token fingerprint + expiry recorded on the device
  → device uses device token for telemetry / log / file / forward endpoints
  → each authenticated request updates last_seen_at and token.last_use_at
```

## File Serving with Fallback

`GET /api/file/{project}/{device}/{filename}` looks for a device-specific file first, then falls back to a project-wide default. This lets you distribute common firmware / config to all devices while allowing per-device overrides. Conditional caching is fully supported via both `If-None-Match` (ETag) and `If-Modified-Since` (`Last-Modified`) — either results in `304 Not Modified` when unchanged; per RFC 7232 §3.3, `If-None-Match` takes precedence when a request sends both.

`PUT /api/file/{project}/{device}/{filename}` writes to the device-specific path atomically (via a temp file). The filename must contain only `[a-zA-Z0-9_\-.]` and must not contain `..`.

### Editing files in the UI

The **Files** tab browses the same directories with a drill-down editor. The device tab shows the device's *effective* file set — its own files layered over the project's, inherited entries marked with a `project` chip and the same precedence the API applies. Writes never reach the project directory: saving an inherited file is a **copy-on-write** into the device directory, so the project file and every other device using it stay untouched. Inherited entries therefore have no delete button; deleting a device override makes the inherited file reappear.

What a file opens as:

| File | Default view | Also available |
|---|---|---|
| JSON with an approved schema | **Form** | Raw (CodeMirror) |
| Flat JSON, no schema | Raw | Form (types inferred from the values) |
| Non-flat JSON, recognised text | Raw | — |
| Image (png/jpg/gif/webp ≤ 2 MB) | Preview | — |
| Anything else | — | download only |

"Flat JSON" means a top-level object whose values are all scalars or string arrays. Saving the **form** writes back only the fields it shows and preserves every other key in the file, so a schema that covers part of a document is data-safe; the raw editor writes the whole document verbatim.

### Schema-driven JSON forms

A sibling `<name>.schema.json` describes `<name>.json` and turns its Form view into typed widgets with validation. It is resolved **device directory first, then project directory** — the same fallback as the data files. A device can upload one through the ordinary file API; an operator can write one in the UI.

This is a deliberately small **subset** of JSON Schema, not an implementation of it: a flat `type: object` with `properties`, and every keyword we don't know is ignored, so a richer schema still renders with fewer honoured constraints.

| Schema | Widget | Value |
|---|---|---|
| `type: string` | text input | `str` |
| `type: string` + `enum` | select | `str` from the enum |
| `type: string` + `x-multiline: true` | textarea | `str` |
| `type: string` + `format: "date"` | date picker | ISO-8601 date string |
| `type: integer` | number (integer) | `int` |
| `type: number` | number | `float` |
| `type: boolean` | switch | `bool` |
| `type: array`, `items.type: string` | chips | `list[str]` |

Honoured alongside these: `title`, `description`, `default`, `required`, `minimum`/`maximum`, `maxLength`, `maxItems`. `x-multiline` uses JSON Schema's blessed `x-` extension prefix, since the spec has no standard "multiline" hint.

Not supported: nested objects · arrays of non-strings · `$ref` · `pattern` · `oneOf`/`anyOf`/`allOf`/`if`/`then`. The first three are omissions of scope; `$ref` and `pattern` are refused on purpose — see the schema-trust bullet in [SECURITY.md](../SECURITY.md#security-model--what-is-and-is-not-protected).

**Layout.** An optional top-level `x-ui.layout` groups fields into rows: a list of rows, each a list of property names sharing one row (`[["panel", "rotation"], ["image_path"]]`). Names that aren't a property the schema subset produced are dropped, and any property the layout doesn't mention still gets its own row — so a stale or partial hint can reorder/group fields but never hide or duplicate one. Absent or malformed `x-ui.layout` keeps the default: one field per row.

**Approval.** A device holds a valid token, so a schema it uploads is untrusted input that would otherwise shape an admin's form. An uploaded schema is therefore **inert until a user approves it**, and approval is bound to the schema's **content hash**: if the device changes the file, the hash changes, the approval lapses and the UI asks again. A schema created or edited in the UI is admin provenance and is approved at save time. Approved hashes live in `<project>/.schema_approvals.json`.

## Firmware Distribution

Firmware reaches a device in two independent halves. The **device** side fetches its own file through `GET /api/file/{project}/{device}/{filename}` with the ordinary device→project fallback and ETag caching — `firmware.bin` by default, or (arduino4iot >= v3.5.0) `firmware-{board}.bin` with `{board}` substituted from that device's own `IOT_BOARD_ID` build define, letting several hardware variants share one project. The **admin** side is the act of getting those files into the store — either uploaded by hand, or pulled from a public GitHub or GitLab release.

A `.firmware.json` sidecar configures a source per project and, optionally, per device — the device-level card lives on the device's General tab, next to Firmware Seed. Each one is independent and pulls into **its own directory**: the project source writes into the project directory, a device source into that device's. Inheritance is not a configuration concern — it happens at serve time through the file fallback, so a device needs its own source only when it should track a *different* release than the project. `asset_name` names exactly one release asset (default `firmware.bin`) — a project mirroring a release that ships several board-specific files (`firmware-<board>.bin`, and for Web-Serial-Flash also `merged-<board>.bin` / `partitions-<board>.csv` — see "Seed Data" above) needs one device-level source per board (each with its own `asset_name`, all tracking the same repo/release) rather than one project-level source pulling every board's asset at once.

`host` picks GitHub or GitLab; `host_url` additionally points a GitLab source at a self-hosted instance (empty = gitlab.com — GitHub has no equivalent, its API is always `api.github.com`). `repo` is `owner/name` on GitHub, or `group/subgroup/.../name` on GitLab (nested subgroups are a single `repo` value with more than one `/`). Host-specific request shapes (release JSON layout, asset structure, auth headers) live in `app/core/firmware/github.py` / `gitlab.py`; `backend.py` only knows the common per-directory pull/state/auto-pull orchestration and dispatches to whichever module `host` names.

Which release is chosen depends on `channel`:

| `channel` | GitHub | GitLab |
|---|---|---|
| `stable` | the one GitHub marks *latest* (excludes prereleases and drafts) | newest release (GitLab has no draft/prerelease flag to exclude by — see below) |
| `prerelease` | newest by `published_at`, prereleases included | same as `stable` |
| `pinned` | exactly `pinned_tag` | exactly `pinned_tag` |

**"Newer" is decided by tag string, not semver.** The last pulled `tag_name` is recorded in `.firmware.state.json`; a pull happens when the resolved tag differs from it (for `pinned`, when the asset digest changes — except on GitLab, which has no asset digest at all, see below, so a pinned GitLab source only ever re-pulls on a tag change). There is no version-range parsing — that keeps the logic auditable and avoids a semver dependency. Semver-aware constraints, private repositories (GitLab or GitHub) and rollback orchestration are out of scope.

A pull resolves the release, streams the named asset (default `firmware.bin`) under a hard size cap, verifies the host's SHA-256 `digest` when the release provides one, and only then renames it atomically into place. GitHub's release API includes an asset digest; **GitLab's does not**, so integrity verification is local-hash-only for a GitLab source (the download itself is still checked against a download-host allowlist — the *configured* GitLab host only, since a GitLab release "asset link" can point at an arbitrary URL, not necessarily one hosted on the GitLab instance itself). If `mqtt_publish_on_pull` is set on a **device-level** source and the project has MQTT enabled, the new file is pushed to that device immediately.

**Auto-pull** is opt-in per source. A background loop ticks once a minute and honours each source's `auto_pull_interval` (floored at 5 minutes), issuing a **conditional** request with the stored ETag — a `304 Not Modified` costs nothing against the rate limit. Unauthenticated GitHub allows 60 requests/hour per IP, so the remaining budget is logged (warning at ≤ 5 left); GitLab has its own, separate limits (higher on gitlab.com, usually unset on a self-hosted instance) that aren't logged the same way yet.

Which version a device actually *runs* is something only the device knows, so it self-reports it — see [Device API → Reporting firmware version](device-api.md#reporting-firmware-version-optional). The UI contrasts the reported version against the pulled tag per device.

## Size Limits

| Resource | Limit | Config key |
|---|---|---|
| File upload | 10 MiB | `MAX_FILE_UPLOAD_SIZE` |
| Telemetry body | 8 KiB | `MAX_TELEMETRY_SIZE` |
| Log body | 8 KiB | `MAX_LOG_SIZE` |

Requests exceeding the limit are rejected with **413 Content Too Large**.

## Local Telemetry Store

Every call to `POST /api/telemetry` also appends a line to `<device>/.device_metrics.jsonl` (in addition to forwarding to any configured remote backend). The file is capped at 2 000 lines (oldest removed first). The **Device → Data** tab reads this file and renders an interactive Plotly chart with configurable time window and metric selector.

### System-telemetry snapshot

A push with `kind=system` (arduino4iot's `postSystemTelemetry`) additionally has its numeric values (`battery_V`, `wifi_rssi`, `boot_count`, …) and string labels (`firmware_id`, `firmware_sha256`, …) snapshotted into `.runtime.json` as `system_metrics` / `system_labels` / `system_reported_at`. The snapshot is **replaced wholesale** on each `system` push (never merged), so it always mirrors the last write — a field a push omits (e.g. `battery_V` on a device without a battery pin) is simply absent. This gives O(1) access to a device's current system state (shown on the Device Dashboard, and cheap to read one-per-row in a device table) without scanning the JSONL. Only `kind=system` feeds it; other kinds don't touch it. Metrics are capped at 32 per device to bound the file.

## UI Generation via niceview

Forms and tables are not coded by hand. [niceview](https://github.com/clausgf/niceview) inspects Pydantic models and generates NiceGUI widgets. Field metadata (labels, editability, widget type) is expressed via `niceview.Field(...)` annotations on the model. `ModelForm.from_adapter(..., autosave=True)` binds the form to a `JsonAdapter` and saves on every change, removing the need for explicit Save buttons.

## Lenient JSON loading

All config and data files (`.project.json`, `.device.json`, `.alarm_config.json`, `.tokens.json`, etc.) are read via `JsonAdapter` / `lenient_model_load` / `lenient_list_load` from [niceview](https://github.com/clausgf/niceview). The loaders tolerate hand-edited files:

| Situation | Behaviour |
|---|---|
| Malformed JSON | `log.error`, return model defaults |
| Unknown field | `log.error`, ignore the field |
| Bad field value | `log.error`, use model default for that field only |
| Missing required field (no default) | `log.error`, raise (last resort) |
| Bad item in a list | `log.error`, skip that item, keep the rest |

Exceptions are never raised for recoverable errors; each field is treated independently so a single corrupt value never blocks the rest of the document.

## Alarm System

Each project can define alarm rules that are evaluated whenever telemetry arrives or (for the built-in device-offline rule) by a background loop every 60 seconds.

**Metric rules** — configured under *Project → General → Alarms*. Each rule specifies a telemetry kind, metric name, comparison operator (`<`, `=`, `>`), and threshold. The *Kind* and *Metric* fields are comboboxes seeded from the names actually seen in the local telemetry store (the *Metric* list follows the selected *Kind*); a not-yet-observed name can still be typed in. When the condition is met the first time an `AlarmEvent` is created with `is_active=True`. When the condition clears the event is resolved (`is_active=False`). Condition re-fires re-open a resolved event rather than creating a duplicate.

**Device offline rule** — built-in rule that fires when a device's `last_seen_at` is older than the online threshold. Both the threshold and the on/off switch are configured under *Project → General → Alarms → Device Offline*; the threshold is what the project and device dashboards use to show a device as online or offline.

**Acknowledgment** — operators acknowledge individual events or all events at once. An acknowledged and resolved event is automatically pruned from storage on the next save. The **Device → Alarms** tab shows all events for one device; the **Project Dashboard** alarm panel shows project-wide events.

**Device alarm badge** — the project Devices table shows an *Alarms* column with the count of active unacknowledged alarms per device.

Storage: `<project>/.alarm_config.json` (rules) and `<project>/.alarm_events.json` (events), both written atomically.

## System Health

The *Project Dashboard* includes a **System Health** card showing the last known status of each external backend. Services tracked:

| Indicator | Source |
|---|---|
| MQTT | `connection_status` from `app/mqtt/backend.py` |
| Telemetry | Last write attempt to the configured remote backend (Prometheus / InfluxDB) |
| Logging | Last write attempt to the configured log backend (Loki / file) |
| Firmware | Last `pull_firmware()` attempt, aggregated across the project and all its devices; only shown once a repo is configured somewhere in the project (`project_has_firmware_source()`) |
| Forwarding: *&lt;rule&gt;* | Last `forward()` attempt for that rule; one row per rule that has been used at least once (key `<project>:forwarding:<rule>`) |

External-call errors are caught and recorded via `app/health.py` (`set_health(key, ok, message)`) instead of propagating exceptions. The dashboard card shows a green check or red error icon with the last error message. Non-2xx upstream responses from a forwarding rule are not treated as failures — they are forwarded verbatim to the device — only network-level errors (timeout, connection failure) mark a rule unhealthy.
