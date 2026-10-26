from typing import Annotated

import anyio
import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ai_censur.audio_censor import AudioCensor
from ai_censur.config import JWTSettings, get_jwt_settings
from ai_censur.database.crud import get_user_by_id
from ai_censur.database.models import User
from ai_censur.database.session import get_session
from ai_censur.utils.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[JWTSettings, Depends(get_jwt_settings)],
) -> User:
    """Resolve the bearer token to a user that still exists in the database."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = decode_access_token(token, settings)
    except jwt.InvalidTokenError as exc:
        raise unauthorized from exc
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise unauthorized
    return user


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
