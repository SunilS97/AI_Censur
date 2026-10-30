import logging
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any
from uuid import UUID

from celery import Task, chain
from celery.result import AsyncResult

from ai_censur.audio_censor import AudioCensor
from ai_censur.worker.tasks import celery_app

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_audio_censor() -> AudioCensor:
    """Load the WhisperX models once per worker process, on the first task."""
    return AudioCensor()


class AudioTask(Task):
    """Base for every audio task: failures are delegated to `AudioCensor.on_failure`."""

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        einfo: Any,
    ) -> None:
        try:
            get_audio_censor().on_failure(exc, task_id, args, kwargs, einfo)
        except Exception:
            logger.exception("Failure handler crashed for task %s", task_id)


def _parse_audio_id(audio_id: str) -> UUID:
    # JSON has no UUID type, so the ID travels as a string.
    return UUID(audio_id)


@celery_app.task(
    base=AudioTask, name="ai_censur.transcribe_audio_task", ignore_result=True
)
def transcribe_audio_task(audio_id: str) -> None:
    """Transcribe the audio and store the word segments."""
    parsed_id = _parse_audio_id(audio_id)
    get_audio_censor().run_transcription(parsed_id)


@celery_app.task(
    base=AudioTask, name="ai_censur.detect_profanity_task", ignore_result=True
)
def detect_profanity_task(audio_id: str) -> None:
    """Flag profanity and the user's words in the stored transcription."""
    parsed_id = _parse_audio_id(audio_id)
    get_audio_censor().run_detection(parsed_id)


@celery_app.task(base=AudioTask, name="ai_censur.render_audio_task", ignore_result=True)
def render_audio_task(audio_id: str) -> None:
    """Render the censored audio from the user's settings and complete the record."""
    parsed_id = _parse_audio_id(audio_id)
    get_audio_censor().run_render(parsed_id)


def queue_audio_processing(audio_id: UUID) -> AsyncResult:
    """Queue transcribe -> detect -> render for one audio.

    Immutable signatures (`si`) give every task just the audio ID; a failing task
    stops the chain and its `on_failure` marks the audio as failed.
    """
    return chain(
        transcribe_audio_task.si(str(audio_id)),
        detect_profanity_task.si(str(audio_id)),
        render_audio_task.si(str(audio_id)),
    ).apply_async()


def queue_audio_reprocessing(audio_id: UUID, *, redetect: bool) -> AsyncResult:
    """Re-run the later stages of an already transcribed audio.

    `redetect` is needed only when the user's word list changed; otherwise the
    stored flags are still valid and just the render runs again.
    """
    signatures = [render_audio_task.si(str(audio_id))]
    if redetect:
        signatures.insert(0, detect_profanity_task.si(str(audio_id)))
    return chain(*signatures).apply_async()
