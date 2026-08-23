# Vendored: esp-web-tools

Prebuilt browser bundle from npm `esp-web-tools@10.4.0` (`dist/web/*` — the
self-contained, no-bundler-needed build; not `dist/*`, which has bare
`import "lit"` etc. for use with a bundler). Vendored rather than loaded from
a CDN so the admin UI keeps working in an offline/air-gapped deployment.

Registers the `<esp-web-install-button>` custom element used by the
Web-Serial-Flash dialog (`app/core/seed/ui.py`). Served at
`/static/esp-web-tools/` (see `app/main.py`).

To update: download `esp-web-tools-<version>.tgz` from npm, replace this
directory's `*.js` and `LICENSE` with the new `dist/web/*` and `LICENSE`,
update the version above and re-check the manifest schema hasn't changed
(https://github.com/esphome/esp-web-tools README).
