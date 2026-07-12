from .base import AuthProvider


class NoAuthProvider(AuthProvider):
    """
    No authentication at all, e.g. for local development. The base class
    already behaves anonymously.
    """
