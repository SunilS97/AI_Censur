from pathlib import Path
from typing import Any, NotRequired, TypedDict

import whisperx
from better_profanity import profanity
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


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    sample_audio_path = project_root / "sample.wav"
    audio_censor = AudioCensor()
    transcription = audio_censor.transcribe_audio(str(sample_audio_path))
    print_json(data=audio_censor.detect_profanity(transcription["word_segments"]))
