from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Body of every error response (`{"detail": "..."}`)."""

    detail: str
