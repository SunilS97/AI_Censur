from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

from ai_censur.api.schemas.common import ErrorResponse
from ai_censur.utils.constants import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH


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


SIGNUP_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    409: {
        "model": ErrorResponse,
        "description": "An account with this email already exists.",
    },
    422: {"description": "Invalid email or password."},
    500: {"model": ErrorResponse, "description": "Creating the account failed."},
}
