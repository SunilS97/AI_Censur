from pathlib import Path

from ai_censur.audio_censor import AudioCensor
from ai_censur.utils.constants import CENSORED_PREFIX
from ai_censur.utils.files import reserve_path


def censor_saved_audio(
    audio_censor: AudioCensor, directory: Path, stored_name: str
) -> str:
    """Transcribe, flag profanity and beep it out; returns the censored file name."""
    input_path = directory / stored_name
    censored_path = reserve_path(
        directory, f"{CENSORED_PREFIX}{input_path.stem}", input_path.suffix
    )
    try:
        transcription = audio_censor.transcribe_audio(str(input_path))
        word_segments = audio_censor.detect_profanity(transcription["word_segments"])
        audio_censor.mute_audio(
            word_segments, str(input_path), str(censored_path), beep=True
        )
    except BaseException:
        censored_path.unlink(missing_ok=True)
        raise
    return censored_path.name
