import logging
from pathlib import Path
from typing import Annotated
from uuid import UUID

import anyio
import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from ai_censur.api.dependencies import get_audio_service, get_current_user
from ai_censur.api.schemas import (
    AUDIO_NOT_FOUND_RESPONSES,
    CENSOR_ERROR_RESPONSES,
    UPDATE_AUDIO_ERROR_RESPONSES,
    AudioCreateResponse,
    AudioRead,
    CensorOptions,
)
from ai_censur.database.crud import (
    delete_audio_record,
    get_audio_for_user,
    save_audio_record,
)
from ai_censur.database.models import Audio, User
from ai_censur.database.session import get_session
from ai_censur.services.audio import (
    AudioNotEditableError,
    AudioNotFoundError,
    AudioService,
    ProcessingQueueUnavailableError,
    SoundEffectNotFoundError,
)
from ai_censur.utils.constants import ALLOWED_AUDIO_EXTENSIONS, UPLOAD_DIR
from ai_censur.utils.files import read_upload, remove_files, sanitize_stem, write_file
from ai_censur.worker.processing import queue_audio_processing

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/censor",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AudioCreateResponse,
    responses=CENSOR_ERROR_RESPONSES,
    summary="Queue an audio file for censoring",
    description=(
        "Requires a valid `Authorization: Bearer <token>` header. "
        "Upload an audio file (`.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`; max 50 MB). "
        "The file is saved to `Uploads/` and queued for a background worker; the "
        "record is returned immediately with status `pending`. Poll "
        "`GET /audio/{id}` to follow `pending` -> `processing` -> `completed` "
        "(or `failed`); `censored_file_path` is set once it completes."
    ),
)
async def censor(
    file: UploadFile,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
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
        audio = await save_audio_record(
            session, stored_name, f"{UPLOAD_DIR.name}/{stored_name}", current_user.id
        )
    except Exception as exc:
        logger.exception("Failed to store the audio record")
        # Avoid orphaned files that have no database record.
        await anyio.to_thread.run_sync(remove_files, UPLOAD_DIR, [stored_name])
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store the audio record.",
        ) from exc

    try:
        # The record is committed first, so the worker can always find it.
        await anyio.to_thread.run_sync(queue_audio_processing, audio.id)
    except Exception as exc:
        logger.exception("Failed to queue audio %s for processing", audio.id)
        try:
            await delete_audio_record(session, audio)
        except Exception:
            logger.exception("Failed to remove unqueued audio record %s", audio.id)
        await anyio.to_thread.run_sync(remove_files, UPLOAD_DIR, [stored_name])
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The processing queue is unavailable. Please try again later.",
        ) from exc

    return audio


@router.get(
    "/audio/{audio_id}",
    response_model=AudioRead,
    responses=AUDIO_NOT_FOUND_RESPONSES,
    summary="Get a stored audio record",
    description=(
        "Fetch a single audio record by its UUID. "
        "Requires a valid bearer token, and the audio must belong to the "
        "authenticated user; otherwise the response is 404."
    ),
)
async def read_audio(
    audio_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Audio:
    try:
        audio = await get_audio_for_user(session, audio_id, current_user.id)
    except Exception as exc:
        logger.exception("Failed to read audio %s", audio_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read the audio record.",
        ) from exc
    if audio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio not found.",
        )
    return audio


@router.patch(
    "/audio/{audio_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AudioRead,
    responses=UPDATE_AUDIO_ERROR_RESPONSES,
    summary="Change how an audio is censored",
    description=(
        "Requires a valid bearer token, and the audio must belong to the "
        "authenticated user. Send any of `user_list`, `use_beep` and "
        "`sound_effect_id`; omitted fields keep their stored value. A changed "
        "`user_list` re-runs profanity detection and the render; any other change "
        "re-runs only the render. The audio goes back to `processing` and the "
        "censored file is replaced when it completes. Only `completed` or `failed` "
        "audio with a transcription can be changed (otherwise 409)."
    ),
)
async def update_audio(
    audio_id: UUID,
    options: CensorOptions,
    service: Annotated[AudioService, Depends(get_audio_service)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Audio:
    try:
        return await service.update_audio(current_user.id, audio_id, options)
    except AudioNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio not found.",
        ) from exc
    except SoundEffectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sound effect not found.",
        ) from exc
    except AudioNotEditableError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The audio is still being processed or has no transcription yet.",
        ) from exc
    except ProcessingQueueUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The processing queue is unavailable. Please try again later.",
        ) from exc
    except Exception as exc:
        logger.exception("Failed to update audio %s", audio_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update the audio.",
        ) from exc
