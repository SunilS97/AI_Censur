import logging
import math
from pathlib import Path
from typing import Any, NotRequired, TypedDict
from uuid import UUID

import whisperx
from better_profanity import profanity
from pydub import AudioSegment
from pydub.generators import Sine
from sqlalchemy import Engine, create_engine, update
from sqlalchemy.orm import Session
from sqlmodel import col

from ai_censur.database.models import Audio, AudioStatus
from ai_censur.database.session import DatabaseSettings
from ai_censur.utils.constants import CENSORED_PREFIX, UPLOAD_DIR
from ai_censur.utils.files import reserve_path

logger = logging.getLogger(__name__)


class Word(TypedDict):
    word: str
    start: float
    end: float
    score: float
    flagged: NotRequired[bool]


def create_sync_engine() -> Engine:
    """Synchronous engine for Celery workers, which run plain blocking tasks.

    It reuses the API's database settings but swaps the asyncpg driver for psycopg2.
    """
    url = DatabaseSettings().url.set(drivername="postgresql+psycopg2")
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2)


class AudioCensor:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or create_sync_engine()
        self.model_name = "small.en"
        self.language = "en"
        self.device = "cpu"
        self.compute_type = "int8"
        self.batch_size = 4

        self.model = whisperx.load_model(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
            language=self.language,
        )
        self.align_model, self.align_metadata = whisperx.load_align_model(
            language_code=self.language,
            device=self.device,
        )

    def censor_file(self, directory: Path, stored_name: str) -> str:
        """Transcribe, flag profanity and beep it out; returns the censored file name."""
        input_path = directory / stored_name
        censored_path = reserve_path(
            directory, f"{CENSORED_PREFIX}{input_path.stem}", input_path.suffix
        )
        try:
            transcription = self.transcribe_audio(str(input_path))
            word_segments = self.detect_profanity(transcription["word_segments"])
            self.mute_audio(
                word_segments, str(input_path), str(censored_path), beep=True
            )
        except BaseException:
            censored_path.unlink(missing_ok=True)
            raise
        return censored_path.name

    def process_audio(self, audio_id: UUID) -> AudioStatus | None:
        """Run the pending -> processing -> completed/failed workflow for one record.

        Returns the final status, or None when the record is missing or was already
        claimed (so a duplicate delivery never censors the same audio twice).
        """
        stored_path = self._claim_audio(audio_id)
        if stored_path is None:
            return None

        censored_name: str | None = None
        try:
            # Only the file name is trusted, so a stored path cannot leave Uploads/.
            censored_name = self.censor_file(UPLOAD_DIR, Path(stored_path).name)
            self._finish_audio(
                audio_id, AudioStatus.COMPLETED, f"{UPLOAD_DIR.name}/{censored_name}"
            )
        except Exception:
            logger.exception("Censoring failed for audio %s", audio_id)
            if censored_name is not None:
                (UPLOAD_DIR / censored_name).unlink(missing_ok=True)
            return self._mark_failed(audio_id)
        logger.info("Audio %s censored", audio_id)
        return AudioStatus.COMPLETED

    def _claim_audio(self, audio_id: UUID) -> str | None:
        # The status guard makes the pending -> processing move atomic.
        statement = (
            update(Audio)
            .where(col(Audio.id) == audio_id, col(Audio.status) == AudioStatus.PENDING)
            .values(status=AudioStatus.PROCESSING)
            .returning(col(Audio.uncensored_file_path))
        )
        with Session(self.engine) as session, session.begin():
            stored_path = session.execute(statement).scalar_one_or_none()
        if stored_path is None:
            logger.warning("Audio %s is missing or not pending; skipping", audio_id)
        return stored_path

    def _finish_audio(
        self, audio_id: UUID, status: AudioStatus, censored_file_path: str | None
    ) -> None:
        statement = (
            update(Audio)
            .where(col(Audio.id) == audio_id)
            .values(status=status, censored_file_path=censored_file_path)
        )
        with Session(self.engine) as session, session.begin():
            session.execute(statement)

    def _mark_failed(self, audio_id: UUID) -> AudioStatus | None:
        try:
            self._finish_audio(audio_id, AudioStatus.FAILED, None)
        except Exception:
            logger.exception("Could not mark audio %s as failed", audio_id)
            return None
        return AudioStatus.FAILED

    def transcribe_audio(self, audio_file_path: str) -> dict[str, Any]:
        if not isinstance(audio_file_path, str):
            raise TypeError("audio_file_path must be a string")

        audio_path = Path(audio_file_path)
        if not audio_path.is_file():
            raise FileNotFoundError(f"Audio file does not exist: {audio_file_path}")

        audio = whisperx.load_audio(str(audio_path))
        transcription = self.model.transcribe(
            audio,
            batch_size=self.batch_size,
            language=self.language,
        )
        segments = transcription["segments"]
        if not segments:
            return {"segments": [], "word_segments": []}

        aligned_transcription = whisperx.align(
            segments,
            self.align_model,
            self.align_metadata,
            audio,
            self.device,
        )
        aligned_segments = [
            dict(segment) for segment in aligned_transcription["segments"]
        ]
        word_segments = [
            dict(word)
            for segment in aligned_segments
            for word in segment.get("words", [])
        ]
        return {
            "segments": aligned_segments,
            "word_segments": word_segments,
        }

    def detect_profanity(self, word_segments: list[Word]) -> list[Word]:
        for word_segment in word_segments:
            word_text = word_segment.get("word")
            if not isinstance(word_text, str):
                raise TypeError("Each word segment must contain a string 'word' field")

            word_segment["flagged"] = profanity.contains_profanity(word_text)

        return word_segments

    def mute_audio(
        self,
        word_segments: list[Word],
        input_audio_path: str,
        output_audio_path: str,
        beep: bool = False,
    ) -> Path:
        if not isinstance(input_audio_path, str):
            raise TypeError("input_audio_path must be a string")
        if not isinstance(output_audio_path, str):
            raise TypeError("output_audio_path must be a string")
        if not isinstance(beep, bool):
            raise TypeError("beep must be a boolean")

        input_path = Path(input_audio_path)
        output_path = Path(output_audio_path)
        if not input_path.is_file():
            raise FileNotFoundError(
                f"Input audio file does not exist: {input_audio_path}"
            )
        if input_path.resolve() == output_path.resolve():
            raise ValueError("Output audio path must differ from the input audio path")
        if not output_path.suffix:
            raise ValueError("Output audio path must include a file extension")
        if not output_path.parent.is_dir():
            raise FileNotFoundError(
                f"Output directory does not exist: {output_path.parent}"
            )

        with input_path.open("rb") as input_file:
            audio = AudioSegment.from_file(input_file, format=input_path.suffix[1:])
        for word_segment in word_segments:
            flagged = word_segment.get("flagged", False)
            if not isinstance(flagged, bool):
                raise TypeError("Each word segment's 'flagged' field must be a boolean")
            if not flagged:
                continue

            start = word_segment.get("start")
            end = word_segment.get("end")
            if (
                isinstance(start, bool)
                or not isinstance(start, (int, float))
                or not math.isfinite(start)
            ):
                raise TypeError(
                    "Flagged word segments must have a finite numeric 'start'"
                )
            if (
                isinstance(end, bool)
                or not isinstance(end, (int, float))
                or not math.isfinite(end)
            ):
                raise TypeError(
                    "Flagged word segments must have a finite numeric 'end'"
                )
            if start < 0 or end <= start:
                raise ValueError(
                    "Flagged word segment timestamps must satisfy 0 <= start < end"
                )

            start_ms = round(start * 1000)
            end_ms = round(end * 1000)
            if start_ms >= len(audio):
                continue
            end_ms = min(max(end_ms, start_ms + 1), len(audio))
            if beep:
                replacement = (
                    Sine(1000, sample_rate=audio.frame_rate)
                    .to_audio_segment(duration=end_ms - start_ms)
                    .set_channels(audio.channels)
                    .set_sample_width(audio.sample_width)
                )
            else:
                replacement = (
                    AudioSegment.silent(
                        duration=end_ms - start_ms,
                        frame_rate=audio.frame_rate,
                    )
                    .set_channels(audio.channels)
                    .set_sample_width(audio.sample_width)
                )
            audio = audio[:start_ms] + replacement + audio[end_ms:]

        output_format = output_path.suffix[1:].lower()
        # ffmpeg has no "m4a" muxer; the MP4 audio container is called "ipod".
        output_format = {"m4a": "ipod"}.get(output_format, output_format)
        with audio.export(output_path, format=output_format):
            pass
        return output_path
