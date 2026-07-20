# Device API Reference

The contract devices depend on. Changes here are recorded in [CHANGELOG.md](../CHANGELOG.md).

[← Documentation index](README.md) · [Project README](../README.md)

---

# Device API Reference

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

---

# Device Client / Test Tool

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
