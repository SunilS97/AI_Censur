from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
)

from ai_censur.database.models import AudioStatus
from ai_censur.utils.constants import (
    MAX_USER_WORD_LENGTH,
    MAX_USER_WORDS,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
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


class UserCreate(BaseModel):
    """Request body of POST /signup; both fields are required."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(
        description="Email address used to sign in. Stored lower-cased.",
        examples=["jane.doe@example.com"],
    )
    # SecretStr keeps the plain password out of reprs, logs and tracebacks.
    password: SecretStr = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        description=(
            f"Between {PASSWORD_MIN_LENGTH} and {PASSWORD_MAX_LENGTH} characters."
        ),
        examples=["correct horse battery staple"],
    )

    @field_validator("email", mode="before")
    @classmethod
    def _normalise_email(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class UserRead(BaseModel):
    """Response of POST /signup; never includes the password or its hash."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(
        description="ID of the user.",
        examples=["59784ccb-4412-42df-bb67-38f60e06f843"],
    )
    created_at: datetime = Field(
        description="When the account was created (UTC).",
        examples=["2026-04-17T12:50:35.663387"],
    )
    email: EmailStr = Field(examples=["jane.doe@example.com"])


class Token(BaseModel):
    """Standard OAuth2 bearer-token response of POST /login."""

    access_token: str = Field(description="Signed JWT whose `sub` is the user id.")
    token_type: str = Field(default="bearer", examples=["bearer"])


class ErrorResponse(BaseModel):
    detail: str


LOGIN_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Incorrect email or password."},
    422: {"description": "The username or password field is missing."},
    500: {"model": ErrorResponse, "description": "Signing in failed."},
}


SIGNUP_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorResponse,
        "description": "An account with this email already exists.",
    },
    422: {"description": "Invalid email or password."},
    500: {"model": ErrorResponse, "description": "Creating the account failed."},
}

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
