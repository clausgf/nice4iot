# MQTT Support

Topic layout, file delivery over MQTT, and broker configuration.

[← Documentation index](README.md) · [Project README](../README.md)

---

nice4iot maintains a **single persistent MQTT connection** shared across all projects. MQTT is enabled per-project via the `is_mqtt_enabled` flag.

## Topic structure

The topic base is configured per project (default: `/nice4iot/{project}/{device}`). Leading slashes and double slashes are normalised automatically. Substituting the project and device names gives topics like `nice4iot/myproject/sensor1/...`. The supported suffixes are:

| Suffix | Direction | Description |
|---|---|---|
| `telemetry/{kind}` | device → server | JSON payload with numeric measurements |
| `log` | device → server | UTF-8 plain-text log message |
| `upload/{filename}` | device → server | Raw file bytes |
| `download/{filename}` | server → device | File contents (published by nice4iot) |

`{base}/cmd/{name}` for server-to-device commands is planned but not yet implemented.

## File delivery

When a project has MQTT enabled, nice4iot publishes files to devices via the `download/{filename}` topic:

- **Periodic check** — every `mqtt_check_interval_s` seconds (default: 60 s) the watcher loop compares file mtimes against a per-device state file (`.mqtt_file_state.json`) and republishes any file that has changed.
- **Immediate publish** — files edited or uploaded via the UI are published immediately. The **Files** tab shows the last publication timestamp and offers a **force publish** button per file.
- **QoS and retain** — configurable per project. QoS 1 with a persistent device session is recommended. Retained messages allow devices that reconnect while the server is running to receive the latest file immediately.
- **Mosquitto message size** — the broker's own `message_size_limit` (mosquitto.conf) applies independently of nice4iot's `max_upload_size`. The Mosquitto default is 256 MB.

## Configuration

Global MQTT broker settings (server, port, credentials, client ID) are shared across all projects and are configured via the `MQTT_*` environment variables — MQTT is **disabled by default** ([docs/configuration.md](configuration.md#mqtt-broker)). The **Projects** list page shows the live connection status (read-only). Per-project MQTT settings (topic base, QoS, retain, check interval) are in the project's **General** tab under _Files_.

## LoRaWAN / The Things Network

nice4iot's MQTT integration connects to an external MQTT broker using the server/port/credentials from the `MQTT_*` environment variables. To receive TTN messages, set `MQTT_SERVER` to `<tenant>.cloud.thethings.network`. Note that TTN uses a different topic format and JSON payload structure — a payload adapter would be required to bridge TTN messages to nice4iot's expected format.

## Authentication TODO

MQTT authentication is currently managed by the broker. A future version will integrate with Mosquitto's Dynamic Security Plugin to provision per-device credentials automatically from the nice4iot UI.
