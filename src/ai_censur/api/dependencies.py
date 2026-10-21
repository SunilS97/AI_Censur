import anyio
from fastapi import FastAPI, HTTPException, Request, status

from ai_censur.audio_censor import AudioCensor


def get_audio_censor(request: Request) -> AudioCensor:
    audio_censor = getattr(request.app.state, "audio_censor", None)
    if audio_censor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio censoring models are not loaded yet.",
        )
    return audio_censor


def get_processing_limiter(app: FastAPI) -> anyio.CapacityLimiter:
    # The models are shared, so run one censoring job at a time.
    limiter = getattr(app.state, "processing_limiter", None)
    if limiter is None:
        limiter = anyio.CapacityLimiter(1)
        app.state.processing_limiter = limiter
    return limiter
