from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_censur.api.schemas.common import ErrorResponse


class SoundEffectRead(BaseModel):
    """A sound effect as returned by /sfx; never exposes file paths or directories."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(
        description="ID of the sound effect.",
        examples=["59784ccb-4412-42df-bb67-38f60e06f843"],
    )
    created_at: datetime = Field(
        description="When the sound effect was uploaded (UTC).",
        examples=["2026-04-17T12:50:35.663387"],
    )
    name: str = Field(
        description="Display name of the sound effect.", examples=["boing"]
    )


SOUND_EFFECT_ADD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid bearer token."},
    400: {
        "model": ErrorResponse,
        "description": "Missing filename, empty or unreadable file, or blank name.",
    },
    413: {"model": ErrorResponse, "description": "File exceeds the 5 MB limit."},
    415: {
        "model": ErrorResponse,
        "description": "Unsupported type. Allowed: .wav, .mp3, .m4a, .flac, .ogg.",
    },
    422: {"description": "The name is longer than 100 characters."},
    500: {
        "model": ErrorResponse,
        "description": "Saving the file or recording the sound effect failed.",
    },
}

SOUND_EFFECT_LIST_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid bearer token."},
    500: {"model": ErrorResponse, "description": "Reading the sound effects failed."},
}
