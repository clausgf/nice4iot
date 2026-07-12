"""
Authentication provider interface.

nice4iot supports pluggable authentication mechanisms for the admin UI,
selected via the AUTH_PROVIDER setting. UI code only talks to this
interface; how a user is identified (reverse proxy headers, a local
login page, ...) is an implementation detail of the concrete provider.

This only protects the NiceGUI admin UI, not the device REST API, which
has its own separate bearer-token auth (provisioning/device tokens).
"""
from typing import Optional
from fastapi import Request


class AuthProvider:
    """
    Base class for authentication providers. The base implementation is
    an anonymous provider: no user, no login, no logout.
    """

    # whether the UI must redirect unauthenticated users to the login page
    login_required: bool = False

    def get_user(self, request: Optional[Request] = None) -> Optional[str]:
        """
        The name of the authenticated user, or None if unauthenticated.
        """
        return None

    def logout_url(self) -> Optional[str]:
        """
        URL to navigate to for logging out, or None if there is no
        logout for this provider.
        """
        return None

    def logout(self) -> None:
        """
        Provider-side logout side effects (e.g. clearing the session).
        Called before navigating to logout_url().
        """
