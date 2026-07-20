# Contributing

Thanks for your interest in nice4iot. Issues and pull requests are welcome.

## Before you start

For anything larger than a bug fix, please open an issue first. nice4iot has a
fairly opinionated structure (see [Design Decisions](README.md#design-decisions)),
and a short discussion up front saves rework.

## Development setup

```bash
uv sync --group dev
mkdir -p data/projects            # required: the app validates that it exists
uv run uvicorn app.main:app --reload
```

See [Development](README.md#development) in the README for the full picture.

## Project rules

These are enforced in review because they keep the codebase consistent:

- **Blocking filesystem I/O** at API and UI entry points is wrapped with
  `anyio.to_thread.run_sync(...)`. Backend functions stay synchronous — pure and
  easy to test — and async callers do the wrapping.
- **Backend functions raise domain exceptions** from `app.exceptions`
  (`NotFoundError`, `ForbiddenError`, `AuthError`, `AlreadyExistsError`). Never
  import FastAPI or raise `HTTPException` inside a backend function; API
  handlers map domain exceptions via `domain_to_http`.
- **Device API changes go into [CHANGELOG.md](CHANGELOG.md).** Devices in the
  field depend on that contract.
- **Acceptance tests** (`tests/test_acceptance.py`, marked `acceptance`) encode
  the device-facing contract. Don't change them to make a change pass — if a
  change requires touching them, say so explicitly in the pull request.

## Before opening a pull request

```bash
uv run ruff check
uv run pytest
```

Both must pass; CI runs the same two commands. Keep commits focused and explain
*why* in the commit message, not just what.

## Extensions

If you want to add functionality that isn't core device management, consider
writing an extension instead — separately deployed packages can add REST
endpoints, MQTT pub/sub, and UI cards and tabs. See
[docs/extensions.md](docs/extensions.md).

## Licence

nice4iot is licensed under the **GNU Affero General Public License v3.0 or
later**. By contributing, you agree that your contributions are licensed under
the same terms. Note that the AGPL's network clause applies: if you run a
modified version as a network service, you must offer its source to its users.
