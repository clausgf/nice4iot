import datetime
import hashlib
from typing import Annotated

import niceview
from pydantic import BaseModel, ConfigDict, Field, model_validator


TOKEN_CHARS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_!@#$%^&*()-+=<>?'
TOKEN_MIN_LENGTH = 16
TOKEN_FINGERPRINT_LENGTH = 12  # hex chars of the SHA-256 digest kept as an identifier

NOW_FACTORY = lambda: datetime.datetime.now(datetime.timezone.utc)


def token_fingerprint(value: str) -> str:
    """Return a short, non-reversible identifier for a token value.

    Used to record *which* provisioning token a device last used without storing
    the shared secret itself. The same value always yields the same fingerprint,
    so the provisioning-token UI can display it alongside each token to correlate
    a device's recorded fingerprint back to a concrete token.
    """
    if not value:
        return ""
    return hashlib.sha256(value.encode()).hexdigest()[:TOKEN_FINGERPRINT_LENGTH]


class AuthToken(BaseModel):
    """An authentication token with metadata.

    A `name` field existed until 0.28.0. Files still carrying one load fine —
    pydantic ignores unknown keys — and lose it on the next write.
    """

    # validate_assignment keeps `fingerprint` in step with `value` on in-place edits
    # (the UI form writes fields with setattr, not by reconstructing the model).
    model_config = ConfigDict(validate_assignment=True)

    is_active: Annotated[bool,
            Field(description='Inactive tokens are rejected on all authentication attempts.'),
            niceview.Field(label='', tooltip='Whether the token is active or not.')
        ] = True

    value: Annotated[str,
            Field(max_length=1024,
                  description='Cryptographically random token string. Treat as a secret.')
        ] = ""

    expires_at: Annotated[datetime.datetime,
            Field(default_factory=NOW_FACTORY,
                  description='Timestamp when the token expires (UTC, set automatically).')
        ] = Field(default_factory=NOW_FACTORY)

    last_use_at: Annotated[datetime.datetime | None,
            Field(default=None,
                  description='Timestamp of the last successful authentication (UTC, set automatically).'),
            niceview.Field(editable=False)
        ] = None

    created_at: Annotated[datetime.datetime,
            Field(default_factory=NOW_FACTORY,
                  description='Timestamp when the token was created (UTC, set automatically).'),
            niceview.Field(editable=False)
        ] = Field(default_factory=NOW_FACTORY)

    updated_at: Annotated[datetime.datetime,
            Field(default_factory=NOW_FACTORY,
                  description='Timestamp of the last change to this token (UTC, set automatically).'),
            niceview.Field(editable=False)
        ] = Field(default_factory=NOW_FACTORY)

    fingerprint: Annotated[str,
            Field(default='',
                  description='Short SHA-256 fingerprint of the token value, derived automatically. '
                              'Devices record it on provisioning so a device can be traced back to '
                              'the token it used, without exposing the secret. Recomputed on every '
                              'change to the value; any stored value is ignored on load.'),
            niceview.Field(editable=False)
        ] = ''

    @model_validator(mode='after')
    def _sync_fingerprint(self) -> 'AuthToken':
        """Derive `fingerprint` from `value`. Runs on load, on construction, and —
        thanks to validate_assignment — on every field edit. Only assigns when the
        value actually differs, so the re-validation this assignment triggers settles
        after one extra pass instead of recursing."""
        fp = token_fingerprint(self.value)
        if self.fingerprint != fp:
            self.fingerprint = fp
        return self
