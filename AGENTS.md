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
- **Code structure (standing rule):** keep `main.py` as app wiring only. Follow the layered layout: routes in `api/` (`router.py`, `schemas.py`, `dependencies.py`), helpers in `utils/`, persistence in `database/` (`models.py`, `session.py`, `crud.py`). Apply clear logic, precise file and folder names, and strict separation of concerns to all new work, at production quality. Whenever a new file or folder is created, give the user a brief synopsis of why it exists and why it is separated.

## Current project state (keep updated)

- **Stack and tooling:** Python 3.12 (`.python-version`), managed with `uv` (`uv add`, `uv run`; keep `uv.lock` consistent). Lint/format with `uv run ruff check .` and `uv run ruff format .`. Tests are `unittest` (pytest is not installed): `uv run python -m unittest discover -s tests`. The `tests/` folder is git-ignored on purpose (internal verification only), so never re-add it to Git.
- **Layout:** `src/ai_censur/` holds `main.py` (app wiring only: lifespan, static mount, `/docs`, includes the routers), `audio_censor.py` (`AudioCensor`), `api/` (`router.py` with `/censor` and `/audio/{id}`, `user_router.py` with `POST /signup`, `auth_router.py` with `POST /login`, `schemas.py`, `dependencies.py`), `config.py` (`JWTSettings`), `services/` (`auth.py` business logic), `utils/` (`constants.py`, `files.py`, `system.py`, `censoring.py`, `security.py` for Argon2 hashing) and `database/` (`models.py`, `session.py`, `crud.py`, `exceptions.py`). Root folders: `Uploads/` (git-ignored, holds user audio) and `tests/`.
- **Audio pipeline:** `AudioCensor` loads WhisperX `small.en` on CPU once, then provides `transcribe_audio`, `detect_profanity` (better_profanity) and `mute_audio(..., beep=False)` (pydub; beep is a 1 kHz tone).
- **API:**
  - `POST /censor` accepts an upload (wav, mp3, m4a, flac, ogg; max 50 MB), saves it to `Uploads/` under its sanitised original name (a numeric suffix is added if the name is taken), censors it with beeps, and saves `Censored_<name>`. It stores an `Audio` row (project-relative paths such as `Uploads/sample.wav`) through the injected `get_session` dependency and returns the `AudioCreateResponse` schema (`id`, `created_at`, `censored_file_path` = file name only). `GET /audio/{audio_id}` returns `AudioRead` (same fields; 404 if unknown). Neither exposes a URL, directory or the uncensored file.
  - `Uploads/` is served statically at `/uploads`.
  - Scalar API docs are at `/docs`. Swagger and ReDoc are disabled.
  - The startup `lifespan` checks ffmpeg, creates the DB tables, then loads the models, and disposes the engine on shutdown.
- **Database:** PostgreSQL on localhost:5432, database `Censur`, user `postgres`. Settings come from the git-ignored root `.env` (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`; template in `.env.example`). Never read, print or commit the password. The database is fully async: SQLAlchemy `AsyncEngine` with the `asyncpg` driver, and `get_session` yields an `AsyncSession` (`psycopg` is blocked here by Windows Application Control, `asyncpg` works). The `Audio` SQLModel (table `audio`: `id` UUID, `created_at`, `uncensored_file_path`, `censored_file_path`) and the `User` SQLModel (table `users`: `id` UUID, `created_at`, unique `email`, `password_hash`) exist, and the tables are created on startup. `POST /signup` registers users (email lower-cased, password 8-128 chars, hashed with Argon2id through `passlib[argon2]`; 201 `UserRead`, 409 duplicate email).
- **Not built yet:** there is no migration tool (Alembic), no token-protected endpoints yet (`POST /login` issues a JWT with the user id as `sub`, settings `JWT_SECRET`/`JWT_ALGORITHM` in `.env`), and no React frontend. `/uploads` currently exposes original uncensored files too, which must be restricted before any public deployment.
- **Windows environment notes:** FFmpeg was installed with winget. New terminals pick it up, but an already-open terminal may not, and the server falls back to the winget folder if ffmpeg isn't on PATH. PowerShell has no `&&`. Before starting a server, make sure any old one is stopped.
- **User preferences:** do only what is asked and nothing extra. Keep responses concise. Use "recieved" only where the user explicitly asked for it (it is no longer in the API). Ask before choices that change scope.
