# Development

Setting up a working copy, running the app from source, and the checks CI enforces.

[← Documentation index](README.md) · [Project README](../README.md)

---

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync
```

Optional extensions are packaged as extras and are not installed by default.
To enable the [nicepaper](https://github.com/clausgf/nicepaper)
extension (`extensions.epaper`):

```bash
uv sync --extra epaper
```

## Run

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: `http://localhost:8000/docs`

## Test

```bash
uv run pytest
```

## Lint

```bash
uv run ruff check          # report
uv run ruff check --fix    # auto-fix
```

Ruff runs a deliberately conservative rule set (`E9`, `F` — syntax errors and
pyflakes: unused imports, undefined names, broken f-strings); style rules are
off to avoid churn. Generated protobuf modules (`*_pb2.py`) are excluded. CI
runs `ruff check` alongside the test suite.

## Type check

```bash
uv run mypy app
```

`mypy` is pinned below 2.x (`pyproject.toml`) — 2.x reports the same errors as
1.x here, pinning just guards against a future regression. Generated protobuf
modules are excluded, same as ruff; `snappy` and `plotly` have no type stubs
and are ignored via `[[tool.mypy.overrides]]`.
