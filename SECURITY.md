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
- **Device-uploaded content is untrusted, and one piece of it renders in the
  operator's browser.** A device can upload `<name>.schema.json`, which drives a
  form in the management UI. That path is meant to hold, so it is kept narrow: an
  uploaded schema is **inert until a user approves it**, and approval is bound to
  the file's SHA-256 — a device that changes the schema forces re-approval. The
  schema is never turned into a type (no `pydantic.create_model`); it is
  interpreted into a fixed set of widget kinds. Its text reaches only labels,
  descriptions (rendered as tooltips) and option lists, never
  `ui.markdown`/`ui.html`, and never CSS or Quasar props. `$ref` is unsupported (no remote fetch, no SSRF) and `pattern` is ignored
  (no untrusted regex, no ReDoS); schema size and field count are capped. Images
  are shown as inert `data:` URIs and SVG is never inlined. Reported firmware
  versions are likewise displayed but never interpreted (trimmed, capped at 64
  characters).
- **Firmware pulls reach out to GitHub, and only there.** Only `owner/repo` is
  accepted — regex-validated, never a URL — and requests are pinned to
  `api.github.com`, with the asset download following the redirect only to
  GitHub's own asset host under a bounded redirect count. No credentials are ever
  sent, so nothing can leak across that redirect and no secret is written to
  disk; private repositories are out of scope rather than a deferred feature. The
  download is streamed under a hard 64 MiB cap and, when the release carries a
  `digest`, verified against its SHA-256 before the atomic rename. The asset is
  stored verbatim and never parsed or executed. A firmware source can only be
  configured by an authenticated operator; a device can never set one.
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
