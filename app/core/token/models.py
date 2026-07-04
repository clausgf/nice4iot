import datetime
from typing import Annotated

import niceview
from pydantic import BaseModel, Field


TOKEN_CHARS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_!@#$%^&*()-+=<>?'
TOKEN_MIN_LENGTH = 16

NOW_FACTORY = lambda: datetime.datetime.now(datetime.timezone.utc)


class AuthToken(BaseModel):
    """An authentication token with metadata."""

    name: Annotated[str,
            Field(description='Human-readable label to identify this token (e.g. "Factory floor").')
        ] = ""

    is_active: Annotated[bool,
            Field(title='Active',
                  description='Inactive tokens are rejected on all authentication attempts.')
        ] = True

    value: Annotated[str,
            Field(max_length=1024,
                  description='Cryptographically random token string. Treat as a secret.')
        ] = ""

    expires_at: Annotated[datetime.datetime,
            Field(default_factory=NOW_FACTORY,
                  description='Timestamp when the token expires (UTC, set automatically).')
        ]

    last_use_at: Annotated[datetime.datetime | None,
            Field(default=None,
                  description='Timestamp of the last successful authentication (UTC, set automatically).'),
            niceview.Field(editable=False)
        ] = None

    created_at: Annotated[datetime.datetime,
            Field(default_factory=NOW_FACTORY,
                  description='Timestamp when the token was created (UTC, set automatically).'),
            niceview.Field(editable=False)
        ]

    updated_at: Annotated[datetime.datetime,
            Field(default_factory=NOW_FACTORY,
                  description='Timestamp of the last change to this token (UTC, set automatically).'),
            niceview.Field(editable=False)
        ]
