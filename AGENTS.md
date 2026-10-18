# Project Guidelines

## Project goal

Build a full-stack audio censoring application with a FastAPI backend and a React frontend. The intended workflow is to transcribe audio, analyze it to identify content to censor, censor the relevant audio, and patch the edited audio back into the original recording. WhisperX is the planned transcription/alignment technology.

The repository is currently an early Python scaffold. Preserve its existing base structure and architectural patterns; introduce frontend and other components incrementally when a task requires them rather than pre-emptively restructuring the project.

## Engineering expectations

- Implement complete, production-quality behavior with clear, maintainable code and secure defaults. Follow established project patterns and avoid unrelated changes.
- Inspect the existing structure and dependencies before implementation. Add or change dependencies only when required by the current functionality, and keep the lockfile consistent with dependency manifest changes.
- Handle audio and user-provided data with privacy and security in mind; validate inputs and surface errors clearly.
- Validate changes with the smallest relevant tests, checks, or build commands available. Add or update focused tests as functionality is introduced.
- Update the root `progress.md` after each completed task or feature, recording what changed, validation performed, and any remaining manual steps or blockers.
- Ask for clarification when a decision materially affects scope or behavior. Clearly identify any setup or other action the user must perform manually.
