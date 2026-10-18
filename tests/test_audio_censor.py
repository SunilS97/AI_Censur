import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ai_censur.audio_censor import AudioCensor


class AudioCensorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.load_model_patcher = patch(
            "ai_censur.audio_censor.whisperx.load_model",
            return_value=Mock(),
        )
        self.load_align_model_patcher = patch(
            "ai_censur.audio_censor.whisperx.load_align_model",
            return_value=(Mock(), {"language": "en"}),
        )
        self.load_audio_patcher = patch(
            "ai_censur.audio_censor.whisperx.load_audio",
            return_value=Mock(name="audio"),
        )
        self.align_patcher = patch(
            "ai_censur.audio_censor.whisperx.align",
            return_value={"segments": [{"start": 0.0, "end": 1.0, "text": "Hello."}]},
        )
        self.load_model = self.load_model_patcher.start()
        self.load_align_model = self.load_align_model_patcher.start()
        self.load_audio = self.load_audio_patcher.start()
        self.align = self.align_patcher.start()
        self.addCleanup(self.load_model_patcher.stop)
        self.addCleanup(self.load_align_model_patcher.stop)
        self.addCleanup(self.load_audio_patcher.stop)
        self.addCleanup(self.align_patcher.stop)
        self.audio_censor = AudioCensor()

    def test_initializes_cpu_models_once_and_aligns_transcription(self) -> None:
        transcript = [{"start": 0.0, "end": 1.0, "text": "Hello."}]
        self.audio_censor.model.transcribe.return_value = {"segments": transcript}
        audio = Mock(name="audio_data")
        self.load_audio.return_value = audio
        expected_segments = [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "Hello.",
                "words": [
                    {"word": "Hello", "start": 0.1, "end": 0.8, "score": 0.99}
                ],
            }
        ]
        self.align.return_value = {"segments": expected_segments}

        with tempfile.NamedTemporaryFile(suffix=".wav") as audio_file:
            result = self.audio_censor.transcribe_audio(audio_file.name)
            self.audio_censor.transcribe_audio(audio_file.name)

        self.load_model.assert_called_once_with(
            "small.en",
            device="cpu",
            compute_type="int8",
            language="en",
        )
        self.load_align_model.assert_called_once_with(
            language_code="en",
            device="cpu",
        )
        self.assertEqual(
            result,
            {
                "segments": expected_segments,
                "word_segments": expected_segments[0]["words"],
            },
        )
        self.assertEqual(self.load_audio.call_count, 2)
        self.assertEqual(self.align.call_count, 2)

    def test_returns_empty_segments_when_no_speech_is_transcribed(self) -> None:
        self.audio_censor.model.transcribe.return_value = {"segments": []}

        with tempfile.NamedTemporaryFile(suffix=".wav") as audio_file:
            result = self.audio_censor.transcribe_audio(audio_file.name)

        self.assertEqual(result, {"segments": [], "word_segments": []})
        self.align.assert_not_called()

    def test_rejects_non_string_audio_path(self) -> None:
        with self.assertRaisesRegex(TypeError, "audio_file_path must be a string"):
            self.audio_censor.transcribe_audio(Path("audio.wav"))  # type: ignore[arg-type]

    def test_reports_missing_audio_file(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.audio_censor.transcribe_audio("missing-audio.wav")


if __name__ == "__main__":
    unittest.main()
