"""Domain exceptions raised by backend functions.

API handlers catch these and map them to HTTPException with the appropriate
HTTP status code. Backend functions must not import FastAPI.
"""


class Nice4IotError(Exception):
    """Base class for all domain errors."""


class NotFoundError(Nice4IotError):
    """Requested resource does not exist (project, device, file)."""


class ForbiddenError(Nice4IotError):
    """Operation not permitted — project or device inactive, not approved."""


class AlreadyExistsError(Nice4IotError):
    """Resource already exists (name collision on create or rename)."""


class AuthError(Nice4IotError):
    """Authentication failed — token missing, malformed, expired, or not found."""
