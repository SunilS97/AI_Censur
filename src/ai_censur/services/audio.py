import logging
from collections.abc import Iterable
from functools import partial
from uuid import UUID

import anyio.to_thread
from sqlalchemy.ext.asyncio import AsyncSession

from ai_censur.api.schemas import CensorOptions
from ai_censur.database.crud import (
    get_audio_for_user,
    get_sound_effect_for_user,
    update_audio_if_status,
)
from ai_censur.database.models import Audio, AudioStatus
from ai_censur.worker.processing import queue_audio_reprocessing

logger = logging.getLogger(__name__)

# Only a finished (or failed) audio can be re-censored; a running one would race.
_EDITABLE_STATUSES = (AudioStatus.COMPLETED, AudioStatus.FAILED)


class AudioNotFoundError(Exception):
    """No audio with this ID belongs to the user."""


class SoundEffectNotFoundError(Exception):
    """No sound effect with this ID belongs to the user."""


class AudioNotEditableError(Exception):
    """The audio is still processing, or was never transcribed."""


class ProcessingQueueUnavailableError(Exception):
    """The Celery broker could not accept the job."""


def _clean_words(words: Iterable[str] | None) -> list[str] | None:
    """Strip, drop blanks and remove case-insensitive duplicates, keeping the order."""
    cleaned: dict[str, str] = {}
    for word in words or ():
        stripped = word.strip()
        if stripped:
            cleaned.setdefault(stripped.casefold(), stripped)
    return list(cleaned.values()) or None


def _word_set(words: Iterable[str] | None) -> frozenset[str]:
    return frozenset(word.casefold() for word in words or () if word.strip())


class AudioService:
    """Business logic for changing how an existing audio is censored."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def update_audio(
        self, user_id: UUID, audio_id: UUID, options: CensorOptions
    ) -> Audio:
        """Apply new censor options and queue the stages that need to run again.

        Only the fields the client sent are changed. A different word list needs
        profanity detection and a render; any other change needs only the render.
        Raises AudioNotFoundError, SoundEffectNotFoundError, AudioNotEditableError
        or ProcessingQueueUnavailableError.
        """
        audio = await get_audio_for_user(self._session, audio_id, user_id)
        if audio is None:
            raise AudioNotFoundError(audio_id)
        if audio.status not in _EDITABLE_STATUSES or audio.transcription is None:
            raise AudioNotEditableError(audio_id)

        changes = {name: getattr(options, name) for name in options.model_fields_set}
        if "user_list" in changes:
            changes["user_list"] = _clean_words(changes["user_list"])
        sound_effect_id = changes.get("sound_effect_id")
        if sound_effect_id is not None and not await get_sound_effect_for_user(
            self._session, sound_effect_id, user_id
        ):
            raise SoundEffectNotFoundError(sound_effect_id)

        redetect = "user_list" in changes and _word_set(
            changes["user_list"]
        ) != _word_set(audio.user_list)
        previous = {
            "user_list": list(audio.user_list) if audio.user_list else None,
            "use_beep": audio.use_beep,
            "sound_effect_id": audio.sound_effect_id,
            "status": audio.status,
        }

        started = await update_audio_if_status(
            self._session,
            audio_id,
            _EDITABLE_STATUSES,
            {**changes, "status": AudioStatus.PROCESSING},
        )
        if not started:
            # Another request or the worker changed the status since it was read.
            raise AudioNotEditableError(audio_id)

        try:
            await anyio.to_thread.run_sync(
                partial(queue_audio_reprocessing, audio_id, redetect=redetect)
            )
        except Exception as exc:
            logger.exception("Failed to queue audio %s for reprocessing", audio_id)
            await self._restore(audio_id, previous)
            raise ProcessingQueueUnavailableError(audio_id) from exc

        await self._session.refresh(audio)
        return audio

    async def _restore(self, audio_id: UUID, previous: dict[str, object]) -> None:
        """Put the old options and status back after the queue refused the job."""
        try:
            await update_audio_if_status(
                self._session, audio_id, (AudioStatus.PROCESSING,), previous
            )
        except Exception:
            logger.exception(
                "Could not restore audio %s after a queue failure", audio_id
            )
