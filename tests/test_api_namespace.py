"""The /api/* namespace must always answer as an API (JSON), never fall through
to the NiceGUI single-page app that ui.run_with mounts as a catch-all at '/'.

This exercises the *real* application object (app.main:app, NiceGUI mounted).
The conftest `api_app` fixture builds a router-only app without NiceGUI, so the
fall-through-to-UI regression this guards against is invisible to every other
test in the suite — which is exactly why it slipped through before.

TestClient is used without a `with` block on purpose: that skips the lifespan,
so no MQTT / watcher / alarm background tasks start. Only routing is exercised.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_wrong_method_on_known_api_path_returns_json_not_html():
    # /api/provision is POST-only; a GET must not be served the NiceGUI page.
    resp = client.get("/api/provision")
    assert "application/json" in resp.headers["content-type"]
    assert resp.status_code == 404


def test_unknown_api_path_returns_json_404():
    resp = client.get("/api/does/not/exist")
    assert resp.status_code == 404
    assert "application/json" in resp.headers["content-type"]


def test_real_post_still_reaches_the_api():
    # 422 (validation error) proves the request reached the provision endpoint
    # rather than being swallowed by the catch-all guard or the UI mount.
    resp = client.post("/api/provision", json={})
    assert resp.status_code == 422
    assert "application/json" in resp.headers["content-type"]
