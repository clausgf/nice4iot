from functools import lru_cache

from app.config import app_config
from .base import AuthProvider
from .none import NoAuthProvider
from .password import PasswordAuthProvider
from .proxy import ProxyAuthProvider

__all__ = ["AuthProvider", "NoAuthProvider", "PasswordAuthProvider", "ProxyAuthProvider", "get_auth_provider"]


@lru_cache
def get_auth_provider() -> AuthProvider:
    """
    The provider selected by the AUTH_PROVIDER setting.
    """
    providers = {
        "none": NoAuthProvider,
        "proxy": ProxyAuthProvider,
        "password": PasswordAuthProvider,
    }
    return providers[app_config.auth_provider]()
