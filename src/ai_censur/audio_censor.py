import json
import logging
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NotRequired, TypedDict
from uuid import UUID

import whisperx
from better_profanity import profanity
from pydub import AudioSegment
from pydub.generators import Sine
from sqlalchemy import Engine, create_engine, select, update
from sqlalchemy.orm import Session
from sqlmodel import col

from ai_censur.database.models import Audio, AudioStatus, SoundEffect
from ai_censur.database.session import DatabaseSettings
from ai_censur.utils.constants import CENSORED_PREFIX, SOUND_EFFECT_DIR, UPLOAD_DIR
from ai_censur.utils.files import reserve_path

logger = logging.getLogger(__name__)

# Keeps letters, digits, underscores and apostrophes, so "Damn!," matches "damn".
_WORD_NOISE = re.compile(r"[^\w']")


class Word(TypedDict):
    word: str
    start: float
    end: float
    score: float
    flagged: NotRequired[bool]


@dataclass(frozen=True, slots=True)
class _ClaimedAudio:
    """What a stage needs from the audio row it just moved to `processing`."""

    audio_path: str
    transcription: list[Word] | None
    use_beep: bool
    user_list: list[str] | None
    sound_effect_path: str | None
    censored_file_path: str | None


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

    def run_transcription(self, audio_id: UUID) -> None:
        """Stage 1: pending -> processing; transcribe and store the word segments."""
        claimed = self._claim_audio(audio_id, AudioStatus.PENDING)
        if claimed is None:
            return
        words = self.transcribe_audio(str(self._stored_path(claimed.audio_path)))[
            "word_segments"
        ]
        self._store_transcription(audio_id, words)
        logger.info("Audio %s transcribed", audio_id)

    def run_detection(self, audio_id: UUID) -> None:
        """Stage 2: flag default profanity and the user's words in the transcription."""
        claimed = self._claim_audio(audio_id, AudioStatus.PROCESSING)
        if claimed is None:
            return
        words = self.detect_profanity(
            self._require_transcription(audio_id, claimed), claimed.user_list
        )
        self._store_transcription(audio_id, words)
        logger.info("Audio %s analysed", audio_id)

    def run_render(self, audio_id: UUID) -> None:
        """Stage 3: censor the flagged words, then processing -> completed."""
        claimed = self._claim_audio(audio_id, AudioStatus.PROCESSING)
        if claimed is None:
            return
        words = self._require_transcription(audio_id, claimed)
        input_path = self._stored_path(claimed.audio_path)
        censored_path = reserve_path(
            UPLOAD_DIR, f"{CENSORED_PREFIX}{input_path.stem}", input_path.suffix
        )
        sound_effect_path = (
            str(SOUND_EFFECT_DIR / Path(claimed.sound_effect_path).name)
            if claimed.sound_effect_path
            else None
        )
        try:
            self.mute_audio(
                words,
                str(input_path),
                str(censored_path),
                beep=claimed.use_beep,
                sound_effect_path=sound_effect_path,
            )
            self._finish_audio(
                audio_id,
                AudioStatus.COMPLETED,
                f"{UPLOAD_DIR.name}/{censored_path.name}",
            )
        except BaseException:
            censored_path.unlink(missing_ok=True)
            raise
        # A re-render (after the user changed the options) replaces the old output.
        if claimed.censored_file_path:
            previous_name = Path(claimed.censored_file_path).name
            if previous_name != censored_path.name:
                (UPLOAD_DIR / previous_name).unlink(missing_ok=True)
        logger.info("Audio %s censored", audio_id)

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        einfo: Any = None,
    ) -> None:
        """Central failure handler: find the audio from the task arguments, mark it failed.

        Workers delegate here so no task handles failures itself. It never raises,
        because it runs inside Celery's failure path.
        """
        audio_id = self._audio_id_from_arguments(args, kwargs)
        if audio_id is None:
            logger.error(
                "Task %s failed without a valid audio id (args=%r): %s",
                task_id,
                args,
                exc,
            )
            return
        logger.error("Task %s failed for audio %s", task_id, audio_id, exc_info=exc)
        try:
            self._mark_failed(audio_id)
        except Exception:
            logger.exception("Could not mark audio %s as failed", audio_id)

    @staticmethod
    def _audio_id_from_arguments(
        args: Sequence[Any], kwargs: Mapping[str, Any]
    ) -> UUID | None:
        raw_id = kwargs.get("audio_id", args[0] if args else None)
        try:
            return UUID(str(raw_id))
        except ValueError:
            return None

    @staticmethod
    def _stored_path(stored_path: str) -> Path:
        # Only the file name is trusted, so a stored path cannot leave Uploads/.
        return UPLOAD_DIR / Path(stored_path).name

    @staticmethod
    def _require_transcription(audio_id: UUID, claimed: "_ClaimedAudio") -> list[Word]:
        if claimed.transcription is None:
            raise ValueError(f"Audio {audio_id} has no stored transcription")
        return claimed.transcription

    def _claim_audio(
        self, audio_id: UUID, expected_status: AudioStatus
    ) -> "_ClaimedAudio | None":
        """Atomically move an audio to `processing` and load what the stage needs.

        The status guard makes a duplicate delivery, or a stage run on an audio
        that already failed or completed, a no-op that returns None.
        """
        statement = (
            update(Audio)
            .where(col(Audio.id) == audio_id, col(Audio.status) == expected_status)
            .values(status=AudioStatus.PROCESSING)
            .returning(
                col(Audio.uncensored_file_path),
                col(Audio.transcription),
                col(Audio.use_beep),
                col(Audio.user_list),
                col(Audio.sound_effect_id),
                col(Audio.censored_file_path),
            )
        )
        with Session(self.engine) as session, session.begin():
            row = session.execute(statement).one_or_none()
            if row is None:
                logger.warning(
                    "Audio %s is missing or not %s; skipping",
                    audio_id,
                    expected_status.value,
                )
                return None
            sound_effect_path = (
                session.execute(
                    select(col(SoundEffect.file_path)).where(
                        col(SoundEffect.id) == row.sound_effect_id
                    )
                ).scalar_one_or_none()
                if row.sound_effect_id is not None
                else None
            )
        return _ClaimedAudio(
            audio_path=row.uncensored_file_path,
            transcription=row.transcription,
            use_beep=row.use_beep,
            user_list=row.user_list,
            sound_effect_path=sound_effect_path,
            censored_file_path=row.censored_file_path,
        )

    def _store_transcription(self, audio_id: UUID, words: list[Word]) -> None:
        # Round-trip through JSON so numpy scalars from WhisperX become plain floats.
        serialisable = json.loads(json.dumps(words, default=float))
        self._update_audio(audio_id, transcription=serialisable)

    def _finish_audio(
        self, audio_id: UUID, status: AudioStatus, censored_file_path: str | None
    ) -> None:
        self._update_audio(
            audio_id, status=status, censored_file_path=censored_file_path
        )

    def _mark_failed(self, audio_id: UUID) -> None:
        # Never overwrite a completed audio, even if a late failure arrives.
        statement = (
            update(Audio)
            .where(
                col(Audio.id) == audio_id,
                col(Audio.status).in_((AudioStatus.PENDING, AudioStatus.PROCESSING)),
            )
            .values(status=AudioStatus.FAILED)
        )
        with Session(self.engine) as session, session.begin():
            session.execute(statement)

    def _update_audio(self, audio_id: UUID, **values: Any) -> None:
        with Session(self.engine) as session, session.begin():
            session.execute(
                update(Audio).where(col(Audio.id) == audio_id).values(**values)
            )

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

    def detect_profanity(
        self,
        word_segments: list[Word],
        custom_words: Iterable[str] | None = None,
    ) -> list[Word]:
        """Flag default profanity plus any of the user's own words (whole words only)."""
        blocked = {
            normalised
            for custom_word in custom_words or ()
            if (normalised := self._normalise_word(custom_word))
        }
        for word_segment in word_segments:
            word_text = word_segment.get("word")
            if not isinstance(word_text, str):
                raise TypeError("Each word segment must contain a string 'word' field")

            word_segment["flagged"] = (
                profanity.contains_profanity(word_text)
                or self._normalise_word(word_text) in blocked
            )

        return word_segments

    @staticmethod
    def _normalise_word(word: str) -> str:
        return _WORD_NOISE.sub("", word).casefold()

    @staticmethod
    def _load_sound_effect(path: Path, reference: AudioSegment) -> AudioSegment:
        if not path.is_file():
            raise FileNotFoundError(f"Sound effect file does not exist: {path}")
        with path.open("rb") as effect_file:
            effect = AudioSegment.from_file(effect_file, format=path.suffix[1:])
        if len(effect) == 0:
            raise ValueError("Sound effect file contains no audio")
        return (
            effect.set_frame_rate(reference.frame_rate)
            .set_channels(reference.channels)
            .set_sample_width(reference.sample_width)
        )

    def mute_audio(
        self,
        word_segments: list[Word],
        input_audio_path: str,
        output_audio_path: str,
        beep: bool = False,
        sound_effect_path: str | None = None,
    ) -> Path:
        """Replace flagged words with a sound effect, a beep or silence (in that order).

        A sound effect longer than the word is cut to fit; a shorter one is followed
        by silence, so the original word is never audible and the timing is kept.
        """
        if not isinstance(input_audio_path, str):
            raise TypeError("input_audio_path must be a string")
        if not isinstance(output_audio_path, str):
            raise TypeError("output_audio_path must be a string")
        if not isinstance(beep, bool):
            raise TypeError("beep must be a boolean")
        if sound_effect_path is not None and not isinstance(sound_effect_path, str):
            raise TypeError("sound_effect_path must be a string")

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
        sound_effect = (
            self._load_sound_effect(Path(sound_effect_path), audio)
            if sound_effect_path
            else None
        )
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
            duration = end_ms - start_ms
            if sound_effect is not None:
                replacement = sound_effect[:duration]
                if len(replacement) < duration:
                    replacement += (
                        AudioSegment.silent(
                            duration=duration - len(replacement),
                            frame_rate=audio.frame_rate,
                        )
                        .set_channels(audio.channels)
                        .set_sample_width(audio.sample_width)
                    )
            elif beep:
                replacement = (
                    Sine(1000, sample_rate=audio.frame_rate)
                    .to_audio_segment(duration=duration)
                    .set_channels(audio.channels)
                    .set_sample_width(audio.sample_width)
                )
            else:
                replacement = (
                    AudioSegment.silent(
                        duration=duration,
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
