from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
)

from ai_censur.utils.constants import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH


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
    censored_file_path: str = Field(
        description="Name of the censored audio file (no directory).",
        examples=["Censored_sample.wav"],
    )

    @field_validator("censored_file_path")
    @classmethod
    def _keep_file_name_only(cls, value: str) -> str:
        return PurePosixPath(PureWindowsPath(value).as_posix()).name


class AudioRead(AudioResponseBase):
    """Response of GET /audio/{audio_id}."""


class AudioCreateResponse(AudioResponseBase):
    """Response of POST /censor."""


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

AUDIO_NOT_FOUND_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid bearer token."},
    404: {"model": ErrorResponse, "description": "No audio exists with this ID."},
    422: {"description": "The ID is not a valid UUID."},
}

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
        "description": "Saving, censoring or recording the audio failed.",
    },
    503: {
        "model": ErrorResponse,
        "description": "Censoring models are not loaded yet.",
    },
}
