# Documentation

[← Project README](../README.md)

## Using nice4iot

- **[What is an IoT manager?](what-is-an-iot-manager.md)** — the problem nice4iot
  solves, for readers new to the category.
- **[Core Concepts](concepts.md)** — data storage, the two-tier token model,
  device lifecycle, file fallback, alarms, and system health.
- **[Device API Reference](device-api.md)** — the REST contract devices depend
  on, plus the `device_client.py` simulator for testing without hardware.
- **[Configuration](configuration.md)** — environment variables and management-UI
  authentication (`none` / `proxy` / `password`).
- **[MQTT Support](mqtt.md)** — topic layout, file delivery, broker settings.

## Deploying

- **[Deployment](../deploy/README.md)** — container image and Docker Compose
  examples (standalone, behind Caddy, with the epaper extension), including the
  security note to read before exposing nice4iot to a network.
- **[Security policy](../SECURITY.md)** — the intended security boundaries and
  how to report a vulnerability.

## Extending and contributing

- **[Architecture](architecture.md)** — module layout and the design decisions
  behind it (filesystem storage, sync I/O in an async app, caching).
- **[Extensions](extensions.md)** — adding REST endpoints, MQTT pub/sub, and UI
  cards or tabs from a separately deployed package.
- **[Development](development.md)** — setup, running from source, tests, linting.
- **[Contributing](../CONTRIBUTING.md)** — the rules enforced in review.
