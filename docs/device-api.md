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

Interactive API docs: `http://localhost:8000/docs`

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
