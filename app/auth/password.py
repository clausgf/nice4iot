from typing import Optional
import bcrypt
from fastapi import Request
from nicegui import app

from app.config import app_config
from app.util import logger
from .base import AuthProvider


# verified against when the username is unknown, so the response time
# does not reveal whether a username exists
_DUMMY_HASH = bcrypt.hashpw(b"invalid", bcrypt.gensalt())


class PasswordAuthProvider(AuthProvider):
    """
    Local username/password login backed by an htpasswd file with bcrypt
    hashes. Manage users with the standard Apache tool:

        htpasswd -B [-c] data/htpasswd <username>

    Only bcrypt entries are supported (htpasswd's default MD5 scheme is
    weak and not accepted). The file is re-read on every login attempt,
    so changes take effect without a restart. The logged-in username is
    kept in the NiceGUI user session storage (cookie signed with
    NICEGUI_STORAGE_SECRET).
    """

    login_required = True

    def get_user(self, request: Optional[Request] = None) -> Optional[str]:
        return app.storage.user.get('username')

    def logout_url(self) -> Optional[str]:
        from app.routes import login_url
        return login_url()

    def logout(self) -> None:
        app.storage.user.pop('username', None)

    def login(self, username: str) -> None:
        app.storage.user['username'] = username

    def verify(self, username: str, password: str) -> bool:
        """
        Check the credentials against the htpasswd file. CPU bound
        (bcrypt); call via asyncio.to_thread from async code.
        """
        users = self._load_users()
        stored_hash = users.get(username)
        if stored_hash is None:
            bcrypt.checkpw(password.encode(), _DUMMY_HASH)
            return False
        return bcrypt.checkpw(password.encode(), stored_hash.encode())

    def _load_users(self) -> dict:
        users = {}
        try:
            with open(app_config.auth_htpasswd_file, 'r') as f:
                lines = f.readlines()
        except OSError as e:
            logger.warning(f"Cannot read htpasswd file {app_config.auth_htpasswd_file}: {e}")
            return users

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#') or ':' not in line:
                continue
            username, stored_hash = line.split(':', 1)
            if stored_hash.startswith('$2y$'):
                # htpasswd writes the $2y$ prefix; python-bcrypt expects
                # $2b$ (same algorithm)
                stored_hash = '$2b$' + stored_hash[4:]
            if not stored_hash.startswith(('$2a$', '$2b$')):
                logger.warning(f"Ignoring non-bcrypt htpasswd entry for user {username}; recreate it with 'htpasswd -B'")
                continue
            users[username] = stored_hash
        return users
