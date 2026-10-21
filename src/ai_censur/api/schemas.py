from typing import Any

from pydantic import BaseModel, Field


class CensorResponse(BaseModel):
    id: str = Field(
        description="ID of the stored audio record.",
        examples=["3f2b8c1e-5a47-4d0e-9a53-8d7a1c2b4e90"],
    )
    censored_url: str = Field(
        description="URL where the censored audio can be played or downloaded.",
        examples=["http://localhost:8000/uploads/Censored_sample.wav"],
    )


class ErrorResponse(BaseModel):
    detail: str


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
