import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status

from ai_censur.api.dependencies import get_current_user, get_sound_effect_service
from ai_censur.api.schemas import (
    SOUND_EFFECT_ADD_ERROR_RESPONSES,
    SOUND_EFFECT_LIST_ERROR_RESPONSES,
    SoundEffectRead,
)
from ai_censur.database.models import SoundEffect, User
from ai_censur.services.sound_effect import SoundEffectService
from ai_censur.utils.constants import (
    ALLOWED_AUDIO_EXTENSIONS,
    MAX_SOUND_EFFECT_NAME_LENGTH,
    MAX_SOUND_EFFECT_SIZE_BYTES,
)
from ai_censur.utils.files import read_upload, sanitize_stem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sfx", tags=["sound effects"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SoundEffectRead,
    responses=SOUND_EFFECT_ADD_ERROR_RESPONSES,
    summary="Upload a sound effect",
    description=(
        "Requires a valid bearer token. Upload a short audio clip (`.wav`, `.mp3`, "
        "`.m4a`, `.flac`, `.ogg`; max 5 MB) to use instead of the beep when "
        "censoring. `name` is optional and defaults to the file name."
    ),
)
async def add_sound_effect(
    file: UploadFile,
    service: Annotated[SoundEffectService, Depends(get_sound_effect_service)],
    current_user: Annotated[User, Depends(get_current_user)],
    name: Annotated[str | None, Form(max_length=MAX_SOUND_EFFECT_NAME_LENGTH)] = None,
) -> SoundEffect:
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

    display_name = name.strip() if name is not None else sanitize_stem(file.filename)
    if not display_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Name must not be blank.",
        )

    try:
        content = await read_upload(file, MAX_SOUND_EFFECT_SIZE_BYTES)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to read uploaded sound effect")
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
        return await service.add_sound_effect(
            current_user.id, display_name, file.filename, content
        )
    except Exception as exc:
        logger.exception("Failed to store the sound effect")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store the sound effect.",
        ) from exc


@router.get(
    "",
    response_model=list[SoundEffectRead],
    responses=SOUND_EFFECT_LIST_ERROR_RESPONSES,
    summary="List my sound effects",
    description=(
        "Requires a valid bearer token. Returns only the authenticated user's "
        "sound effects, oldest first."
    ),
)
async def read_all_sound_effects(
    service: Annotated[SoundEffectService, Depends(get_sound_effect_service)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[SoundEffect]:
    try:
        return await service.read_all_sound_effects(current_user)
    except Exception as exc:
        logger.exception("Failed to read sound effects")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read the sound effects.",
        ) from exc
