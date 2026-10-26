import anyio.to_thread
from sqlalchemy.ext.asyncio import AsyncSession

from ai_censur.database.crud import get_user_by_email
from ai_censur.database.models import User
from ai_censur.utils.security import DUMMY_PASSWORD_HASH, verify_password


async def authenticate_user(
    session: AsyncSession, email: str, password: str
) -> User | None:
    """Return the user when the credentials are valid, otherwise None.

    A hash is verified even for unknown emails so both failure modes cost the same.
    """
    user = await get_user_by_email(session, email.strip().lower())
    password_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    is_valid = await anyio.to_thread.run_sync(verify_password, password, password_hash)
    return user if user and is_valid else None
