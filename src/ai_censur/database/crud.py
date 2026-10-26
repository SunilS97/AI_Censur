from uuid import UUID

import anyio.to_thread
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from ai_censur.database.exceptions import EmailAlreadyRegisteredError
from ai_censur.database.models import Audio, User
from ai_censur.utils.security import hash_password


async def save_audio_record(
    session: AsyncSession, uncensored_file_path: str, censored_file_path: str
) -> Audio:
    audio = Audio(
        uncensored_file_path=uncensored_file_path,
        censored_file_path=censored_file_path,
    )
    session.add(audio)
    try:
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    return audio


async def get_audio_by_id(session: AsyncSession, audio_id: UUID) -> Audio | None:
    return await session.get(Audio, audio_id)


async def get_user_by_id(session: AsyncSession, user_id: UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(col(User.email) == email))
    return result.scalar_one_or_none()


async def add_user(session: AsyncSession, email: str, password: str) -> User:
    """Hash the password with Argon2 and store the new user.

    The unique index on `email` is the source of truth for duplicates, which keeps
    this race-free when two sign-ups for the same address arrive together.
    """
    password_hash = await anyio.to_thread.run_sync(hash_password, password)
    user = User(email=email, password_hash=password_hash)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise EmailAlreadyRegisteredError(email) from exc
    except BaseException:
        await session.rollback()
        raise
    return user
