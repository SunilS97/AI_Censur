import logging
import os
import re
import shutil
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path, PureWindowsPath
from typing import Annotated, Any

import anyio
import anyio.to_thread
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, status
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from scalar_fastapi import get_scalar_api_reference

from ai_censur.audio_censor import AudioCensor

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIR = PROJECT_ROOT / "Uploads"
UPLOADS_URL_PATH = "/uploads"
CENSORED_PREFIX = "Censored_"
MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024
READ_CHUNK_SIZE_BYTES = 1024 * 1024
ALLOWED_AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".flac", ".ogg"})
SUCCESS_MESSAGE = "successfully censored the file"
MAX_STEM_LENGTH = 100
MAX_NAME_COLLISION_ATTEMPTS = 1000
_UNSAFE_CHARS = re.compile(r"[^\w.\- ]")
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10))}
    | {f"LPT{i}" for i in range(1, 10)}
)


def _ensure_ffmpeg_available() -> None:
    """Fail fast if ffmpeg is missing, since WhisperX and pydub shell out to it.

    On Windows, winget installs update PATH only for newly opened terminals, so a
    long-running shell can miss a valid install; fall back to the winget location.
    """
    if shutil.which("ffmpeg"):
        return
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        winget_packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        for executable in sorted(winget_packages.glob("*/*/bin/ffmpeg.exe")):
            os.environ["PATH"] = f"{executable.parent}{os.pathsep}{os.environ['PATH']}"
            logger.info("ffmpeg not on PATH; using %s", executable)
            return
    raise RuntimeError(
        "ffmpeg was not found. Install it (for example "
        "'winget install Gyan.FFmpeg.Essentials') and restart the terminal "
        "before starting the server."
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    _ensure_ffmpeg_available()
    # Models are expensive to load, so build the AudioCensor once per process.
    app.state.audio_censor = await anyio.to_thread.run_sync(AudioCensor)
    yield


class CensorResponse(BaseModel):
    message: str = Field(examples=[SUCCESS_MESSAGE])
    censored_url: str = Field(
        description="URL where the censored audio can be played or downloaded.",
        examples=["http://localhost:8000/uploads/Censored_sample.wav"],
    )


class ErrorResponse(BaseModel):
    detail: str


CENSOR_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {
        "model": ErrorResponse,
        "description": "Missing filename, empty or unreadable file.",
    },
    413: {"model": ErrorResponse, "description": "File exceeds the 50 MB limit."},
    415: {
        "model": ErrorResponse,
        "description": "Unsupported type. Allowed: .wav, .mp3, .m4a, .flac, .ogg.",
    },
    500: {
        "model": ErrorResponse,
        "description": "Saving or censoring the audio failed.",
    },
    503: {
        "model": ErrorResponse,
        "description": "Censoring models are not loaded yet.",
    },
}

API_DESCRIPTION = """
Upload an audio file and receive a censored copy in which profane words are
replaced with a beep.

**Pipeline:** upload -> WhisperX transcription and alignment -> profanity
detection -> beep over flagged words -> censored file stored in `Uploads/`.
"""

app = FastAPI(
    title="AI Censur",
    description=API_DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount(UPLOADS_URL_PATH, StaticFiles(directory=UPLOAD_DIR), name="uploads")


def get_audio_censor(request: Request) -> AudioCensor:
    audio_censor = getattr(request.app.state, "audio_censor", None)
    if audio_censor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio censoring models are not loaded yet.",
        )
    return audio_censor


def _get_processing_limiter(app: FastAPI) -> anyio.CapacityLimiter:
    # The models are shared, so run one censoring job at a time.
    limiter = getattr(app.state, "processing_limiter", None)
    if limiter is None:
        limiter = anyio.CapacityLimiter(1)
        app.state.processing_limiter = limiter
    return limiter


async def _read_upload(file: UploadFile) -> bytes:
    content = bytearray()
    while chunk := await file.read(READ_CHUNK_SIZE_BYTES):
        content.extend(chunk)
        if len(content) > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"File exceeds the maximum size of "
                    f"{MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB."
                ),
            )
    return bytes(content)


def _sanitize_stem(filename: str) -> str:
    # PureWindowsPath treats both "/" and "\" as separators, dropping any directory part.
    stem = PureWindowsPath(filename).stem
    stem = _UNSAFE_CHARS.sub("_", stem).strip(" ._")[:MAX_STEM_LENGTH]
    if not stem:
        return "audio"
    if stem.split(".")[0].upper() in _WINDOWS_RESERVED_NAMES:
        return f"_{stem}"
    return stem


def _reserve_path(directory: Path, stem: str, extension: str) -> Path:
    """Exclusively create an empty file, appending _1, _2, ... when the name is taken."""
    directory.mkdir(parents=True, exist_ok=True)
    for counter in range(MAX_NAME_COLLISION_ATTEMPTS):
        name = f"{stem}{extension}" if counter == 0 else f"{stem}_{counter}{extension}"
        path = directory / name
        try:
            path.open("xb").close()
        except FileExistsError:
            continue
        return path
    raise FileExistsError(f"Could not find a free filename for {stem}{extension}")


def _write_file(directory: Path, stem: str, extension: str, content: bytes) -> str:
    path = _reserve_path(directory, stem, extension)
    try:
        path.write_bytes(content)
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return path.name


def _censor_saved_audio(
    audio_censor: AudioCensor, directory: Path, stored_name: str
) -> str:
    """Transcribe, flag profanity and beep it out; returns the censored file name."""
    input_path = directory / stored_name
    censored_path = _reserve_path(
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


@app.get("/docs", include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title="AI Censur API Reference",
    )


@app.post(
    "/censor",
    status_code=status.HTTP_200_OK,
    response_model=CensorResponse,
    responses=CENSOR_ERROR_RESPONSES,
    summary="Censor profanity in an audio file",
    description=(
        "Upload an audio file (`.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`; max 50 MB). "
        "The file is saved to `Uploads/`, transcribed, and every profane word is "
        "replaced with a beep. The censored copy is saved as `Censored_<name>` and "
        "its URL is returned. Processing runs on CPU, so allow several seconds."
    ),
)
async def censor(
    request: Request,
    file: UploadFile,
    audio_censor: Annotated[AudioCensor, Depends(get_audio_censor)],
) -> dict[str, str]:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must have a filename.",
        )

    extension = Path(file.filename).suffix.lower()
    if extension not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                "Unsupported file type. Allowed: "
                f"{', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}."
            ),
        )

    try:
        content = await _read_upload(file)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to read uploaded file")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not read the uploaded file.",
        ) from exc
    finally:
        await file.close()

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    try:
        stored_name = await anyio.to_thread.run_sync(
            _write_file,
            UPLOAD_DIR,
            _sanitize_stem(file.filename),
            extension,
            content,
        )
    except OSError as exc:
        logger.exception("Failed to save uploaded file")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save the uploaded file.",
        ) from exc

    try:
        censored_name = await anyio.to_thread.run_sync(
            _censor_saved_audio,
            audio_censor,
            UPLOAD_DIR,
            stored_name,
            limiter=_get_processing_limiter(request.app),
        )
    except Exception as exc:
        logger.exception("Failed to censor uploaded audio")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to censor the uploaded audio.",
        ) from exc

    return {
        "message": SUCCESS_MESSAGE,
        "censored_url": str(request.url_for("uploads", path=censored_name)),
    }
