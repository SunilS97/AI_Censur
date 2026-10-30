from collections.abc import Collection, Mapping
from typing import Any
from uuid import UUID

import anyio.to_thread
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from ai_censur.database.exceptions import EmailAlreadyRegisteredError
from ai_censur.database.models import Audio, AudioStatus, SoundEffect, User
from ai_censur.utils.security import hash_password


async def save_sound_effect_record(
    session: AsyncSession, name: str, file_path: str, user_id: UUID
) -> SoundEffect:
    sound_effect = SoundEffect(name=name, file_path=file_path, user_id=user_id)
    session.add(sound_effect)
    try:
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    return sound_effect


async def save_audio_record(
    session: AsyncSession, name: str, uncensored_file_path: str, user_id: UUID
) -> Audio:
    """Store a new upload as `pending` for its owner; the Celery worker does the rest."""
    audio = Audio(name=name, uncensored_file_path=uncensored_file_path, user_id=user_id)
    session.add(audio)
    try:
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    return audio


async def delete_audio_record(session: AsyncSession, audio: Audio) -> None:
    await session.delete(audio)
    try:
        await session.commit()
    except BaseException:
        await session.rollback()
        raise


async def get_audio_for_user(
    session: AsyncSession, audio_id: UUID, user_id: UUID
) -> Audio | None:
    """Return the audio only when it belongs to the user.

    Ownership is part of the query, so another user's audio is indistinguishable
    from a missing one.
    """
    result = await session.execute(
        select(Audio).where(col(Audio.id) == audio_id, col(Audio.user_id) == user_id)
    )
    return result.scalar_one_or_none()


async def get_sound_effect_for_user(
    session: AsyncSession, sound_effect_id: UUID, user_id: UUID
) -> SoundEffect | None:
    """Return the sound effect only when it belongs to the user."""
    result = await session.execute(
        select(SoundEffect).where(
            col(SoundEffect.id) == sound_effect_id,
            col(SoundEffect.user_id) == user_id,
        )
    )
    return result.scalar_one_or_none()


async def update_audio_if_status(
    session: AsyncSession,
    audio_id: UUID,
    allowed_statuses: Collection[AudioStatus],
    values: Mapping[str, Any],
) -> bool:
    """Apply `values` only while the audio is in one of `allowed_statuses`.

    The status guard is part of the UPDATE, so two requests racing on the same audio
    cannot both start processing it. Returns False when nothing was updated.
    """
    statement = (
        update(Audio)
        .where(
            col(Audio.id) == audio_id,
            col(Audio.status).in_(tuple(allowed_statuses)),
        )
        .values(**values)
        .returning(col(Audio.id))
    )
    try:
        updated = (await session.execute(statement)).scalar_one_or_none()
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    return updated is not None


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
