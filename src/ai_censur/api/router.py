import logging
from pathlib import Path
from typing import Annotated
from uuid import UUID

import anyio
import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from ai_censur.api.dependencies import (
    get_audio_censor,
    get_current_user,
    get_processing_limiter,
)
from ai_censur.api.schemas import (
    AUDIO_NOT_FOUND_RESPONSES,
    CENSOR_ERROR_RESPONSES,
    AudioCreateResponse,
    AudioRead,
)
from ai_censur.audio_censor import AudioCensor
from ai_censur.database.crud import get_audio_by_id, save_audio_record
from ai_censur.database.models import Audio
from ai_censur.database.session import get_session
from ai_censur.utils.censoring import censor_saved_audio
from ai_censur.utils.constants import ALLOWED_AUDIO_EXTENSIONS, UPLOAD_DIR
from ai_censur.utils.files import read_upload, remove_files, sanitize_stem, write_file

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/censor",
    status_code=status.HTTP_200_OK,
    response_model=AudioCreateResponse,
    responses=CENSOR_ERROR_RESPONSES,
    dependencies=[Depends(get_current_user)],
    summary="Censor profanity in an audio file",
    description=(
        "Requires a valid `Authorization: Bearer <token>` header. "
        "Upload an audio file (`.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`; max 50 MB). "
        "The file is saved to `Uploads/`, transcribed, and every profane word is "
        "replaced with a beep. The censored copy is saved as `Censored_<name>` and "
        "the stored audio record is returned. Processing runs on CPU, so allow "
        "several seconds."
    ),
)
async def censor(
    request: Request,
    file: UploadFile,
    audio_censor: Annotated[AudioCensor, Depends(get_audio_censor)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Audio:
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
        content = await read_upload(file)
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
            write_file,
            UPLOAD_DIR,
            sanitize_stem(file.filename),
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
            censor_saved_audio,
            audio_censor,
            UPLOAD_DIR,
            stored_name,
            limiter=get_processing_limiter(request.app),
        )
    except Exception as exc:
        logger.exception("Failed to censor uploaded audio")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to censor the uploaded audio.",
        ) from exc

    try:
        audio = await save_audio_record(
            session,
            f"{UPLOAD_DIR.name}/{stored_name}",
            f"{UPLOAD_DIR.name}/{censored_name}",
        )
    except Exception as exc:
        logger.exception("Failed to store the audio record")
        # Avoid orphaned files that have no database record.
        await anyio.to_thread.run_sync(
            remove_files, UPLOAD_DIR, [stored_name, censored_name]
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store the audio record.",
        ) from exc

    return audio


@router.get(
    "/audio/{audio_id}",
    response_model=AudioRead,
    responses=AUDIO_NOT_FOUND_RESPONSES,
    dependencies=[Depends(get_current_user)],
    summary="Get a stored audio record",
    description=(
        "Fetch a single audio record by its UUID. "
        "Requires a valid `Authorization: Bearer <token>` header."
    ),
)
async def read_audio(
    audio_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Audio:
    audio = await get_audio_by_id(session, audio_id)
    if audio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio not found.",
        )
    return audio
