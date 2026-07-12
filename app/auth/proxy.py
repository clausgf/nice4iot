from typing import Optional
from fastapi import Request

from app.config import app_config
from .base import AuthProvider


class ProxyAuthProvider(AuthProvider):
    """
    Authentication is done by a reverse proxy in front of the app (e.g.
    Caddy with oauth2-proxy); the app only reads the identity the proxy
    forwards in request headers. The headers are only trustworthy when
    the app is reachable exclusively through the proxy.
    """

    def get_user(self, request: Optional[Request] = None) -> Optional[str]:
        if request is None:
            return None
        for header in app_config.auth_user_headers:
            value = request.headers.get(header)
            if value:
                return value
        return None

    def logout_url(self) -> Optional[str]:
        # ends the proxy session, e.g. oauth2-proxy's /oauth2/sign_out
        return app_config.auth_logout_url
