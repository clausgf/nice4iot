- Never change acceptance tests without asking!
- Before every commit, run and fix `ruff check`, `mypy extensions`, and `pytest` (in `.venv`). Then update the docs. Finally, commit and push. Increase only the lowest possible digit of the tag, prefer patches over minor over major releases if justifiable.
- Only commit if explicitly ordered so.
- When unsure, ask before committing and pushing.
- Ask before removing dead code (commented out, not called, ...).
- Use uv for python package management. Use the python interpreter, pytest etc. from the .venv.
- Always add API changes to CHANGELOG.md.
- Keep docs and code comments short and precise.
- Keep the doc well structured.
- Playwright is available, but not used in regular tests for performance.
- Keep the communication to the user concise and precise. 

## Async IO rule
All blocking filesystem IO at API and UI entry points must be wrapped with
`anyio.to_thread.run_sync(...)`. Backend functions remain synchronous (pure,
easy to test). Callers in async context (`async def` API handlers, NiceGUI
panels) wrap IO-heavy backend calls. The telemetry hot path (`_append_local_metrics`)
is already wrapped in `write_telemetry`.

## Domain exceptions
Backend functions raise domain exceptions from `app.exceptions`
(`NotFoundError`, `ForbiddenError`, `AuthError`, `AlreadyExistsError`).
API handlers import `domain_to_http` from `app.api.dependencies` to map
these to `HTTPException`. Never import FastAPI or raise `HTTPException`
inside a backend function.

