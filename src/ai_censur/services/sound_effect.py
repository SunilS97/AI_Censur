from pathlib import Path
from uuid import UUID

import anyio.to_thread
from sqlalchemy.ext.asyncio import AsyncSession

from ai_censur.database.crud import save_sound_effect_record
from ai_censur.database.models import SoundEffect, User
from ai_censur.utils.constants import SOUND_EFFECT_DIR
from ai_censur.utils.files import remove_files, sanitize_stem, write_file


class SoundEffectService:
    """Stores a user's sound effects: the file on disk plus its database record."""

    def __init__(self, session: AsyncSession, directory: Path | None = None) -> None:
        self._session = session
        self._directory = directory if directory is not None else SOUND_EFFECT_DIR

    async def add_sound_effect(
        self, user_id: UUID, name: str, original_filename: str, content: bytes
    ) -> SoundEffect:
        """Save the file under a sanitised, collision-free name and record it.

        The caller has already validated the upload. If the database write fails the
        file is removed again, so no file is left without a record.
        """
        stored_name = await anyio.to_thread.run_sync(
            write_file,
            self._directory,
            sanitize_stem(original_filename),
            Path(original_filename).suffix.lower(),
            content,
        )
        try:
            return await save_sound_effect_record(
                self._session,
                name,
                f"{self._directory.name}/{stored_name}",
                user_id,
            )
        except Exception:
            await anyio.to_thread.run_sync(remove_files, self._directory, [stored_name])
            raise

    async def read_all_sound_effects(self, user: User) -> list[SoundEffect]:
        """Return the user's sound effects, oldest first, via `User.sound_effects`.

        The relationship is loaded explicitly because lazy loading is not possible
        on an async session.
        """
        await self._session.refresh(user, ["sound_effects"])
        return list(user.sound_effects)
