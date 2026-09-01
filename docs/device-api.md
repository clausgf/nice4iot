# Device API Reference

The contract devices depend on. Changes here are recorded in [CHANGELOG.md](../CHANGELOG.md).

[← Documentation index](README.md) · [Project README](../README.md)

---

All device endpoints require `Authorization: Bearer <device_token>`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/provision` | Obtain a device token |
| `POST` | `/api/telemetry/{project}/{device}/{kind}` | Push numeric measurements (JSON) |
| `POST` | `/api/log/{project}/{device}` | Push log lines (plain text) |
| `GET` | `/api/file/{project}/{device}/{filename}` | Download a file |
| `HEAD` | `/api/file/{project}/{device}/{filename}` | Check file ETag (OTA) |
| `PUT` | `/api/file/{project}/{device}/{filename}` | Upload a file |
| `GET` | `/api/forward/{project}/{device}/{name}/{path}` | Proxy request to configured upstream |

Interactive API docs (Swagger UI): `http://localhost:8000/docs`. Raw OpenAPI
schema (for client codegen, contract tests, ...): `http://localhost:8000/openapi.json`.
This page covers device-facing conventions; the OpenAPI doc is authoritative for
request/response schemas and status codes.

## Reporting firmware version (optional)

On any authenticated request — and on `POST /api/provision` — a device may report
the firmware it is running via two optional headers:

| Header | Meaning |
|---|---|
| `X-Firmware-Version` | The running firmware version (e.g. a release tag `v1.4.0`). |
| `X-Firmware-Commit` | Optional build/commit identifier. |

Both are optional and backward-compatible: omitting them leaves the last reported
value unchanged; they are never required and never affect authentication. The
server stores the latest value per device (capped at 64 characters, whitespace
trimmed) and shows it in the management UI (Device Dashboard, Devices table). The
value is *reported*, not verified — it reflects what the device claims to run.

Alternatively, a device may report the same values **in the telemetry body** as
the reserved string keys `firmware_version` (see
[Telemetry metric names](#telemetry-metric-names)) — useful when adding a JSON
field is easier than a custom header. Body and header are equivalent; if both are
present on one request, the body value wins.

Reporting on **every** request keeps the shown version fresh; reporting **at
provisioning** guarantees a known value at least at each token refresh.

Bake the version into the image at build time so it cannot drift from the actual
build: inject the release tag as a compile-time define (GitHub Actions offers it
as `${{ github.ref_name }}` on a `v*` tag build) and set the header once in the
HTTP client's shared request helper — the same place that sets
`Authorization: Bearer …` — rather than per call. Keep a fallback
(`#ifndef FIRMWARE_VERSION #define FIRMWARE_VERSION "dev"`) so local builds still
compile. See [Core Concepts → Firmware Distribution](concepts.md#firmware-distribution)
for the server side.

## Telemetry metric names

`POST /api/telemetry/{project}/{device}/{kind}` takes a JSON object of numeric
measurements; each key is a metric name. Nested objects are flattened with
underscores (`{"env": {"temp": 22}}` → `env_temp`), and any character outside
`[a-zA-Z0-9_]` is replaced with `_`. Beyond that, two conventions make the data
model behind Prometheus/InfluxDB (see
[Architecture → Telemetry data model](architecture.md#design-decisions)) work
well — they are recommendations for device firmware, not enforced by the server:

- **Put the unit in the name** (Prometheus convention): `temperature_celsius`,
  `pressure_pascals`, `uptime_seconds`, `heap_free_bytes`. Base units, written
  out, no abbreviations. The server recognises common unit suffixes (`seconds`,
  `bytes`, `celsius`, `volts`, `pascals`, …) and forwards them as Prometheus
  UNIT metadata, so dashboards can be self-describing.
- **Suffix counters with `_total`** — a monotonically increasing value like
  `messages_sent_total` is written as a Prometheus *counter*; everything else is
  a *gauge*.
- **Keep a field name's meaning consistent across kinds.** A metric name plus its
  labels must identify one quantity: if `voltage` appears under `kind=power` and
  under `kind=battery`, both must mean the same measured quantity. Use distinct
  names (`supply_voltage`, `battery_voltage`) when they don't — otherwise the two
  kinds collide on one Prometheus series.

### String fields become labels

A **string** value is not a metric — it is treated as a low-cardinality **label**
(a dimension like `firmware_version`, `site`, `hw_rev`). Instead of tagging every
numeric series (which would churn on each change), all string labels of a write are
collected into **one synthetic info series** per write, following the OpenMetrics
`target_info` convention:

| Backend | Numeric value → | String value → | Info carrier |
|---|---|---|---|
| Prometheus / VictoriaMetrics | series `<project>_<field>{device,kind}` | **label** on the info series | series `<project>_target_info{device,kind,…} 1` |
| InfluxDB | field on measurement `<project>` | **tag** on the info point | measurement `<project>_target_info … value=1i` |
| Local store | `v{}` in the JSONL record | key in the record's `l{}` | (kept in the same record) |

Query the version alongside a metric with a label join:

```promql
myproj_temperature_celsius * on(device) group_left(firmware_version) myproj_target_info
```

**Rules and limits.** Keep labels **slowly changing / bounded** — never per-request
values (IDs, timestamps, measurements), or you create series churn / cardinality
blow-up. Label names must match `[a-zA-Z_][a-zA-Z0-9_]*`; values are trimmed and
capped at 128 chars; at most 16 labels per write; `device`/`kind`/`__name__` are
protected; a **numeric** field named `target_info` is dropped (reserved). Other
value types are ignored.

**Reserved keys.** `firmware_version` are ordinary labels but
additionally update the device's reported firmware (equivalent to the `X-Firmware-*`
headers) — so they show up both in Grafana (as labels) and in the nice4iot UI.

In the management UI the **Device → Dashboard** Status card shows the device's
firmware version and board (from the `system`-kind push's cached snapshot, see
below), and the **Data** tab can overlay a vertical marker wherever a chosen
label's value changed (*Label markers* selector, backed by the full local
label history).

### The `system` telemetry kind

`kind=system` is nice4iot-reserved: the server snapshots each push of this
kind wholesale into the device's runtime sidecar (`.runtime.json`) for O(1)
access from the UI (Device Dashboard Status card, Devices table), instead of
scanning the metrics history. A field a push omits is absent from the
snapshot, not stale from a previous push — the snapshot always reflects
exactly the last `system` write.

[arduino4iot](https://github.com/clausgf/arduino4iot)'s `postSystemTelemetry()`
uses this kind and reports these well-known keys — a convention, not enforced
by the server:

| Key | Type | Meaning |
|---|---|---|
| `battery_V` | numeric | Battery voltage. |
| `wifi_rssi` | numeric | Wi-Fi signal strength (dBm). |
| `boot_count` | numeric | Number of boots since first provisioning. |
| `active_ms` | numeric | Time spent awake this cycle (ms). |
| `board` | string (label) | Hardware board identifier. |
| `firmware_version` | string (label) | See [Reporting firmware version](#reporting-firmware-version-optional) — reserved, updates the device's runtime firmware state. |
| `firmware_id`, `firmware_sha256` | string (label) | Optional build identifiers, alongside `firmware_version`. |

A project extension that pushes its own telemetry (e.g. nicepaper's `epaper`
kind) registers its kind via `app.extensions.register_telemetry_cache_kind()`
to get the same wholesale-snapshot caching, keyed by kind, instead of
overloading the reserved `system` kind.

---

## Device Client / Test Tool

`tools/device_client.py` is a Python simulation of an [arduino4iot](https://github.com/clausgf/arduino4iot) device. It implements the same HTTP flow as the C++ library and is useful for integration testing, demos, and load testing without needing real hardware.

```bash
# Full wake-up cycle (provision → config → OTA check → telemetry → log):
uv run python tools/device_client.py cycle \
    --url http://localhost:8000 \
    --project myproject \
    --device mydevice \
    --token <provisioning_token> \
    --sensors '{"temperature": 22.4, "humidity": 60}' \
    --log "Device started"

# Simulate periodic wake-ups every 30 s:
uv run python tools/device_client.py loop --interval 30 \
    --url http://localhost:8000 \
    --project myproject --device mydevice --token <token>

# Push telemetry only:
uv run python tools/device_client.py telemetry sensors \
    '{"temperature": 22.4}' ...

# Upload a config file:
uv run python tools/device_client.py upload myconfig.json ...
```

State (device token + ETag cache) is persisted in `.<device>.state.json` between invocations, mirroring NV-RAM on hardware.
