from typing import Any

from pydantic import BaseModel, Field

from ai_censur.api.schemas.common import ErrorResponse


class Token(BaseModel):
    """Standard OAuth2 bearer-token response of POST /login."""

    access_token: str = Field(description="Signed JWT whose `sub` is the user id.")
    token_type: str = Field(default="bearer", examples=["bearer"])


LOGIN_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Incorrect email or password."},
    422: {"description": "The username or password field is missing."},
    500: {"model": ErrorResponse, "description": "Signing in failed."},
}
