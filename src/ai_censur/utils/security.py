from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from passlib.context import CryptContext

from ai_censur.config import JWTSettings

# Argon2id with passlib's defaults; `deprecated="auto"` lets hashes be upgraded
# transparently if the parameters change later.
_password_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password with Argon2id (CPU-bound; call it off the event loop)."""
    return _password_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_context.verify(password, password_hash)


# Verified against when an email is unknown, so response time does not reveal
# whether an account exists.
DUMMY_PASSWORD_HASH = hash_password("not-a-real-password")


def create_access_token(user_id: UUID, settings: JWTSettings) -> str:
    """Create a signed JWT whose `sub` claim is the user id."""
    issued_at = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(
        payload, settings.secret.get_secret_value(), algorithm=settings.algorithm
    )


def decode_access_token(token: str, settings: JWTSettings) -> UUID:
    """Return the user id from a valid token.

    Raises jwt.InvalidTokenError for a bad signature, expiry, missing claims or a
    non-UUID subject.
    """
    claims = jwt.decode(
        token,
        settings.secret.get_secret_value(),
        algorithms=[settings.algorithm],
        options={"require": ["sub", "exp"]},
    )
    try:
        return UUID(claims["sub"])
    except (ValueError, TypeError, AttributeError) as exc:
        raise jwt.InvalidTokenError("Invalid subject claim.") from exc
