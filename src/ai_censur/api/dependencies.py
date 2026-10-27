from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

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
