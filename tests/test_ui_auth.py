"""
Unit tests for the admin-UI authentication providers (app/auth/, see
app/config.py's auth_provider setting). Unrelated to tests/test_auth.py,
which covers the device REST API's separate bearer-token auth.
"""
import bcrypt
import pytest

from app.config import AppConfig, app_config
from app.auth import get_auth_provider
from app.auth.none import NoAuthProvider
from app.auth.password import PasswordAuthProvider
from app.auth.proxy import ProxyAuthProvider


# ---------------------------------------------------------------------------
# NoAuthProvider
# ---------------------------------------------------------------------------

def test_no_auth_provider_is_anonymous():
    provider = NoAuthProvider()
    assert provider.login_required is False
    assert provider.get_user() is None
    assert provider.logout_url() is None


# ---------------------------------------------------------------------------
# ProxyAuthProvider
# ---------------------------------------------------------------------------

class _FakeRequest:
    def __init__(self, headers: dict) -> None:
        self.headers = headers


def test_proxy_auth_provider_reads_first_matching_header(monkeypatch):
    monkeypatch.setattr(app_config, "auth_user_headers", ["X-User", "X-Fallback"])
    provider = ProxyAuthProvider()
    request = _FakeRequest({"X-Fallback": "alice"})
    assert provider.get_user(request) == "alice"


def test_proxy_auth_provider_no_headers_present():
    provider = ProxyAuthProvider()
    request = _FakeRequest({})
    assert provider.get_user(request) is None


def test_proxy_auth_provider_no_request():
    provider = ProxyAuthProvider()
    assert provider.get_user(None) is None


def test_proxy_auth_provider_logout_url(monkeypatch):
    monkeypatch.setattr(app_config, "auth_logout_url", "/oauth2/sign_out")
    assert ProxyAuthProvider().logout_url() == "/oauth2/sign_out"


# ---------------------------------------------------------------------------
# PasswordAuthProvider
# ---------------------------------------------------------------------------

def _make_password_provider(tmp_path, monkeypatch, lines):
    htpasswd = tmp_path / "htpasswd"
    htpasswd.write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(app_config, "auth_htpasswd_file", str(htpasswd))
    return PasswordAuthProvider()


def test_password_provider_login_required():
    assert PasswordAuthProvider.login_required is True


def test_verify_accepts_correct_password(tmp_path, monkeypatch):
    stored = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
    provider = _make_password_provider(tmp_path, monkeypatch, [f"finn:{stored}"])
    assert provider.verify("finn", "secret")
    assert not provider.verify("finn", "wrong")
    assert not provider.verify("unknown", "secret")


def test_verify_accepts_htpasswd_2y_prefix(tmp_path, monkeypatch):
    stored = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
    stored = "$2y$" + stored[4:]  # htpasswd -B writes the $2y$ prefix
    provider = _make_password_provider(tmp_path, monkeypatch, [f"finn:{stored}"])
    assert provider.verify("finn", "secret")


def test_load_users_skips_comments_and_non_bcrypt(tmp_path, monkeypatch):
    stored = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
    provider = _make_password_provider(tmp_path, monkeypatch, [
        "# a comment",
        "",
        "not-a-valid-line",
        "md5user:$apr1$abcdefgh$0123456789abcdef",
        f"finn:{stored}",
    ])
    users = provider._load_users()
    assert list(users.keys()) == ["finn"]
    assert not provider.verify("md5user", "anything")


def test_missing_htpasswd_file_rejects_everyone(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config, "auth_htpasswd_file", str(tmp_path / "missing"))
    provider = PasswordAuthProvider()
    assert not provider.verify("finn", "secret")


# ---------------------------------------------------------------------------
# get_auth_provider() factory
# ---------------------------------------------------------------------------

def test_get_auth_provider_selects_by_config(monkeypatch):
    get_auth_provider.cache_clear()
    monkeypatch.setattr(app_config, "auth_provider", "none")
    assert isinstance(get_auth_provider(), NoAuthProvider)

    get_auth_provider.cache_clear()
    monkeypatch.setattr(app_config, "auth_provider", "proxy")
    assert isinstance(get_auth_provider(), ProxyAuthProvider)

    get_auth_provider.cache_clear()
    monkeypatch.setattr(app_config, "auth_provider", "password")
    assert isinstance(get_auth_provider(), PasswordAuthProvider)

    get_auth_provider.cache_clear()


def test_default_auth_provider_is_none():
    assert AppConfig.model_fields["auth_provider"].default == "none"
