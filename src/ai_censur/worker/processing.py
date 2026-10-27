import logging
from functools import lru_cache
from uuid import UUID

from ai_censur.audio_censor import AudioCensor
from ai_censur.worker.tasks import celery_app

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_audio_censor() -> AudioCensor:
    """Load the WhisperX models once per worker process, on the first task."""
    return AudioCensor()


@celery_app.task(name="ai_censur.process_audio", ignore_result=True)
def process_audio(audio_id: str) -> None:
    """Censor the stored audio with this ID (UUID string, as JSON has no UUID type)."""
    try:
        parsed_id = UUID(audio_id)
    except (ValueError, TypeError, AttributeError):
        logger.error("process_audio received an invalid audio id: %r", audio_id)
        return
    get_audio_censor().process_audio(parsed_id)
