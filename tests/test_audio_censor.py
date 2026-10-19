import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pydub import AudioSegment
from pydub.generators import Sine

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
                "words": [{"word": "Hello", "start": 0.1, "end": 0.8, "score": 0.99}],
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

    def test_detects_profanity_and_defaults_clean_words_to_not_flagged(self) -> None:
        word_segments = [
            {"word": "Go", "start": 0.0, "end": 0.2, "score": 0.99},
            {"word": "fuck", "start": 0.2, "end": 0.5, "score": 0.95},
            {"word": "yourself.", "start": 0.5, "end": 1.0, "score": 0.92},
        ]

        result = self.audio_censor.detect_profanity(word_segments)  # type: ignore[arg-type]

        self.assertEqual(
            result,
            [
                {
                    "word": "Go",
                    "start": 0.0,
                    "end": 0.2,
                    "score": 0.99,
                    "flagged": False,
                },
                {
                    "word": "fuck",
                    "start": 0.2,
                    "end": 0.5,
                    "score": 0.95,
                    "flagged": True,
                },
                {
                    "word": "yourself.",
                    "start": 0.5,
                    "end": 1.0,
                    "score": 0.92,
                    "flagged": False,
                },
            ],
        )

    def test_rejects_word_segment_without_string_word(self) -> None:
        with self.assertRaisesRegex(TypeError, "string 'word' field"):
            self.audio_censor.detect_profanity(  # type: ignore[arg-type]
                [{"start": 0.0, "end": 1.0, "score": 0.9}]
            )

    def test_mutes_flagged_words_and_preserves_unflagged_audio(self) -> None:
        source_audio = Sine(440).to_audio_segment(duration=1000).apply_gain(-3)

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.wav"
            output_path = Path(temp_dir) / "muted.wav"
            with source_audio.export(input_path, format="wav"):
                pass
            word_segments = [
                {
                    "word": "clean",
                    "start": 0.1,
                    "end": 0.3,
                    "score": 0.99,
                    "flagged": False,
                },
                {
                    "word": "profane",
                    "start": 0.4,
                    "end": 0.6,
                    "score": 0.95,
                    "flagged": True,
                },
            ]

            result_path = self.audio_censor.mute_audio(
                word_segments,
                str(input_path),
                str(output_path),  # type: ignore[arg-type]
            )

            with output_path.open("rb") as output_file:
                muted_audio = AudioSegment.from_file(output_file, format="wav")

        self.assertEqual(result_path, output_path)
        self.assertEqual(len(muted_audio), len(source_audio))
        self.assertEqual(muted_audio[400:600].dBFS, float("-inf"))
        self.assertNotEqual(muted_audio[100:300].dBFS, float("-inf"))

    def test_rejects_output_path_same_as_input(self) -> None:
        with (
            tempfile.NamedTemporaryFile(suffix=".wav") as audio_file,
            self.assertRaisesRegex(ValueError, "must differ"),
        ):
            self.audio_censor.mute_audio(
                [],
                audio_file.name,
                audio_file.name,  # type: ignore[arg-type]
            )

    def test_beeps_flagged_words_and_preserves_unflagged_audio(self) -> None:
        source_audio = Sine(440).to_audio_segment(duration=1000).apply_gain(-3)

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.wav"
            output_path = Path(temp_dir) / "beeped.wav"
            with source_audio.export(input_path, format="wav"):
                pass

            result_path = self.audio_censor.mute_audio(
                [
                    {
                        "word": "profane",
                        "start": 0.4,
                        "end": 0.6,
                        "score": 0.95,
                        "flagged": True,
                    }
                ],
                str(input_path),
                str(output_path),  # type: ignore[arg-type]
                beep=True,
            )

            with output_path.open("rb") as output_file:
                beeped_audio = AudioSegment.from_file(output_file, format="wav")

        self.assertEqual(result_path, output_path)
        self.assertEqual(len(beeped_audio), len(source_audio))
        self.assertNotEqual(beeped_audio[400:600].dBFS, float("-inf"))
        self.assertNotEqual(beeped_audio[100:300].dBFS, float("-inf"))

    def test_rejects_non_boolean_beep_option(self) -> None:
        with (
            tempfile.NamedTemporaryFile(suffix=".wav") as audio_file,
            self.assertRaisesRegex(TypeError, "beep must be a boolean"),
        ):
            self.audio_censor.mute_audio(
                [],
                audio_file.name,
                "output.wav",
                beep=1,  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
