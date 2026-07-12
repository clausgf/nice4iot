# extensions

This directory is a [PEP 420 namespace package](https://peps.python.org/pep-0420/).
It is deliberately empty and must never contain an `__init__.py` — that
would break namespace merging for every installed extension.

Installed extensions contribute their own `extensions/<name>/` package
(e.g. `extensions/epaper/`) via their own distribution; nice4iot discovers
them automatically at startup.

See [`docs/extensions.md`](../docs/extensions.md) for how to write one.
