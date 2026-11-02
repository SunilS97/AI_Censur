from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from ai_censur.api.schemas.common import ErrorResponse
from ai_censur.database.models import AudioStatus
from ai_censur.utils.constants import (
    DEFAULT_SUBTITLE_SYMBOL,
    MAX_SUBTITLE_SYMBOLS,
    MAX_SUBTITLE_VISIBLE_CHARS,
    MAX_USER_WORD_LENGTH,
    MAX_USER_WORDS,
)


class AudioResponseBase(BaseModel):
    """Fields shared by audio responses; never exposes directories or the original file."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(
        description="ID of the stored audio record.",
        examples=["59784ccb-4412-42df-bb67-38f60e06f843"],
    )
    created_at: datetime = Field(
        description="When the audio record was created (UTC).",
        examples=["2026-04-17T12:50:35.663387"],
    )
    censored_file_path: str | None = Field(
        default=None,
        description="Name of the censored audio file (no directory); null until processing completes.",
        examples=["Censored_sample.wav"],
    )
    status: AudioStatus = Field(
        description="Processing state: pending, processing, completed or failed.",
        examples=["pending"],
    )

    @field_validator("censored_file_path")
    @classmethod
    def _keep_file_name_only(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return PurePosixPath(PureWindowsPath(value).as_posix()).name


class AudioRead(AudioResponseBase):
    """Response of GET /audio/{audio_id}."""


class AudioCreateResponse(AudioResponseBase):
    """Response of POST /censor."""

    user_list: list[str] | None = Field(
        default=None,
        description="Extra words to censor on top of the default list; null if none.",
        examples=[["away"]],
    )
    use_beep: bool = Field(
        default=False,
        description="Whether censored words are covered with a beep instead of silence.",
    )
    sound_effect_id: UUID | None = Field(
        default=None,
        description="ID of the sound effect played over censored words; null if none.",
        examples=["9b3ab33f-2003-4edc-abb4-c3c2544f509b"],
    )


class CensorOptions(BaseModel):
    """Body of PATCH /audio/{audio_id}.

    Only the fields that are sent are changed; an omitted field keeps its stored value.
    """

    model_config = ConfigDict(extra="forbid")

    user_list: (
        list[
            Annotated[
                str,
                StringConstraints(
                    strip_whitespace=True, min_length=1, max_length=MAX_USER_WORD_LENGTH
                ),
            ]
        ]
        | None
    ) = Field(
        default=None,
        max_length=MAX_USER_WORDS,
        description=(
            "Extra words to censor, on top of the default profanity list. "
            "Send null or an empty list to clear."
        ),
        examples=[["pineapple", "darn"]],
    )
    use_beep: bool = Field(
        default=False,
        description="Cover censored words with a beep instead of silence.",
    )
    sound_effect_id: UUID | None = Field(
        default=None,
        description=(
            "ID of one of your sound effects (see `GET /sfx`) to play over censored "
            "words. It takes priority over the beep. Send null to clear."
        ),
    )


class SubtitleOptions(BaseModel):
    """Optional body of POST /audio/{audio_id}/subtitle."""

    model_config = ConfigDict(extra="forbid")

    symbol: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SUBTITLE_SYMBOLS,
        description=(
            "One or more symbols used to mask flagged words. With several, one of "
            f"them is picked at random for the whole subtitle. Default `{DEFAULT_SUBTITLE_SYMBOL}`."
        ),
        examples=["*", "#*@"],
    )
    visible_chars: int = Field(
        default=1,
        ge=0,
        le=MAX_SUBTITLE_VISIBLE_CHARS,
        description=(
            "How many leading characters of a flagged word stay visible; at least "
            "one character is always masked."
        ),
        examples=[1, 3],
    )

    @field_validator("symbol")
    @classmethod
    def _printable_symbols_only(cls, value: str | None) -> str | None:
        # Whitespace or control characters would break the SRT cue layout.
        if value is not None and not all(
            char.isprintable() and not char.isspace() for char in value
        ):
            raise ValueError("symbol must not contain whitespace or control characters")
        return value


UPDATE_AUDIO_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid bearer token."},
    404: {
        "model": ErrorResponse,
        "description": (
            "No audio with this ID, or no sound effect with this ID, exists for the "
            "authenticated user."
        ),
    },
    409: {
        "model": ErrorResponse,
        "description": "The audio is still being processed or has no transcription yet.",
    },
    422: {"description": "Invalid ID or options."},
    500: {"model": ErrorResponse, "description": "Updating the audio failed."},
    503: {
        "model": ErrorResponse,
        "description": "The processing queue is unavailable; nothing was changed.",
    },
}

AUDIO_NOT_FOUND_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid bearer token."},
    404: {
        "model": ErrorResponse,
        "description": "No audio with this ID exists for the authenticated user.",
    },
    422: {"description": "The ID is not a valid UUID."},
    500: {"model": ErrorResponse, "description": "Reading the audio failed."},
}

CENSOR_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid bearer token."},
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
        "description": "Saving the upload or recording the audio failed.",
    },
    503: {
        "model": ErrorResponse,
        "description": "The processing queue is unavailable; nothing was stored.",
    },
}

DOWNLOAD_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid bearer token."},
    404: {
        "model": ErrorResponse,
        "description": (
            "No audio with this ID exists for the authenticated user, or its "
            "censored file is no longer available."
        ),
    },
    409: {
        "model": ErrorResponse,
        "description": "The audio has not finished censoring yet (or it failed).",
    },
    422: {"description": "The ID is not a valid UUID."},
    500: {"model": ErrorResponse, "description": "Sending the audio failed."},
}

SUBTITLE_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid bearer token."},
    404: {
        "model": ErrorResponse,
        "description": "No audio with this ID exists for the authenticated user.",
    },
    409: {
        "model": ErrorResponse,
        "description": "The audio has not finished censoring yet (or it failed).",
    },
    422: {"description": "Invalid ID, symbol or visible_chars."},
    500: {"model": ErrorResponse, "description": "Building the subtitle failed."},
}
