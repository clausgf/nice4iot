# Security Policy

## Supported versions

nice4iot is developed on `main`. Security fixes go into `main` and the next
release; older releases are not patched separately.

## Reporting a vulnerability

Please report security issues **privately**, not as a public GitHub issue.

Use [GitHub's private vulnerability reporting](https://github.com/clausgf/nice4iot/security/advisories/new)
for this repository. Include what you found, how to reproduce it, and what an
attacker could achieve with it.

Expect an initial response within a few days. This is a spare-time project, so
please allow reasonable time for a fix before disclosing publicly.

## Security model — what is and is not protected

Understanding the intended boundaries helps judge whether something is a bug:

- **Device REST API** (`/api/*`) — protected by bearer tokens. Devices
  self-register with a project-scoped provisioning token and receive a
  short-lived device token. Tokens are bearer credentials: anyone holding one can
  act as that device, so they must travel over TLS.
- **Management UI** — authentication is **optional and off by default**
  (`AUTH_PROVIDER=none`). This is a deliberate default for local trials, not a
  claim that the UI is safe to expose. An unauthenticated UI reachable from a
  network is a deployment mistake rather than a vulnerability in nice4iot — see
  the security note in [deploy/README.md](deploy/README.md).
- **Two independent auth domains** — the UI auth (`AUTH_PROVIDER`) and the device
  bearer-token auth are separate; the UI login never gates `/api/*`. A blanket
  proxy auth placed in front of the whole app to protect the UI will also block
  `/api/*` and lock out devices, so `/api/*` must be exempted from the proxy's
  login gate. That is a configuration requirement, not a weakened boundary — the
  device API stays bearer-token protected either way.
- **No multi-user separation** — all UI operators share one access level. There
  is no RBAC, and no isolation between projects at the UI level. Privilege
  escalation *between UI users* is therefore not a meaningful boundary today.
- **HTTP forwarding** — the forwarding endpoint strips the `Authorization`
  header but passes other client headers through to the configured backend.
  Treat forwarding targets as trusted.
- **Filesystem storage** — project and device state lives in plain files under
  `data/projects/`. Anyone with read access to that directory can read tokens
  and configuration.

Reports about the defaults above are welcome as regular issues; reports about
ways to bypass a boundary that *is* meant to hold — token forgery, escaping a
device's own scope, injection through telemetry or file paths — belong in a
private advisory.
