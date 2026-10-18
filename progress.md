# Project Progress

## Goal

Build a full-stack audio censoring app with a FastAPI backend and React frontend. The intended pipeline is transcription, AI-assisted content analysis, audio censoring, and patching the censored audio back into the recording. WhisperX is the planned transcription/alignment technology.

## Current status

- The repository is an initial Python package scaffold; no frontend or audio-processing workflow is present yet.
- `pyproject.toml` targets Python 3.12+ and declares `fastapi[all]`, `rich`, `scalar-fastapi`, and `whisperx`; dependencies are locked in `uv.lock`.
- `.python-version` pins the project environment to Python 3.12.
- `src/ai_censur/main.py` contains a placeholder entry point. `src/ai_censur/audio_censor.py` implements CPU transcription and forced alignment. `src/ai_censur/__init__.py` and `README.md` are empty.
- `tests/test_audio_censor.py` contains focused unit tests for the transcription workflow.
- `src/ai_censur/audio_censor.py` can also be run directly to transcribe the root `sample.wav` and print aligned JSON.
- Project-wide coding expectations and the requirement to keep this log current are recorded in `AGENTS.md`.

## Completed

- Established this progress log and recorded the initial repository state and project goal.
- Recorded project-specific implementation, dependency, validation, and documentation expectations in `AGENTS.md`.
- Added WhisperX with `uv add whisperx` (installed version 3.8.6). The initial Python 3.14 installation attempt failed because pandas needed a source build; with user approval, changed the project baseline to Python 3.12 and the installation completed successfully.
- Verified WhisperX imports in the project environment (`Python 3.12.10`) and `uv lock --check` passes.
- Implemented `AudioCensor.transcribe_audio()` with CPU WhisperX transcription and forced alignment. Each instance loads and retains its English transcription and alignment models; results contain aligned `segments` and flattened `word_segments`.
- Added focused unit tests for CPU configuration, model reuse, aligned results, empty transcripts, and invalid or missing file paths.
- Validation: all 4 focused `unittest` tests pass, and `compileall` succeeds for the source and test files.
- Added a guarded direct-execution runner in `audio_censor.py` for `sample.wav`, printing results with Rich `print_json`; declared `rich` as a direct dependency.
- Ran the full CPU transcription and forced alignment successfully on the root `sample.wav`. It returned one segment and word timings. Installed FFmpeg 9.0.1 user-scoped because WhisperX requires the FFmpeg executable to decode audio; after updating the process PATH, the run succeeded. A TorchCodec warning remains, but did not prevent the WhisperX FFmpeg audio-loading path from succeeding.
- Updated the transcription result to return a top-level `segments` list and an independently flattened `word_segments` list. Updated empty-transcript behavior and focused tests accordingly.
- Validation: reran `sample.wav` successfully and confirmed the output includes the original aligned segment structure plus three flattened word segments. All 4 focused unit tests pass; `uv lock --check` and Python compilation pass.

## Next

- Implement features incrementally, preserving the current structure and selecting or adding dependencies when a concrete task needs them.
- Update this log when each task or feature is completed, including relevant validation and any user setup still required.
