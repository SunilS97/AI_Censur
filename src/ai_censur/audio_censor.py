import math
from pathlib import Path
from typing import Any, NotRequired, TypedDict

import whisperx
from better_profanity import profanity
from pydub import AudioSegment
from pydub.generators import Sine
from rich import print_json


class Word(TypedDict):
    word: str
    start: float
    end: float
    score: float
    flagged: NotRequired[bool]


class AudioCensor:
    def __init__(self) -> None:
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
        with audio.export(output_path, format=output_format):
            pass
        return output_path


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    sample_audio_path = project_root / "sample.wav"
    muted_audio_path = project_root / "sample_muted.wav"
    beeped_audio_path = project_root / "sample_beeped.wav"
    audio_censor = AudioCensor()
    transcription = audio_censor.transcribe_audio(str(sample_audio_path))
    word_segments = audio_censor.detect_profanity(transcription["word_segments"])
    print_json(data=word_segments)
    output_path = audio_censor.mute_audio(
        word_segments,
        str(sample_audio_path),
        str(muted_audio_path),
    )
    print(f"Muted audio saved to: {output_path}")
    beeped_output_path = audio_censor.mute_audio(
        word_segments,
        str(sample_audio_path),
        str(beeped_audio_path),
        beep=True,
    )
    print(f"Beeped audio saved to: {beeped_output_path}")
