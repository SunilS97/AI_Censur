import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from ai_censur.api.schemas import LOGIN_ERROR_RESPONSES, Token
from ai_censur.config import JWTSettings, get_jwt_settings
from ai_censur.database.session import get_session
from ai_censur.services.auth import authenticate_user
from ai_censur.utils.security import create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


@router.post(
    "/login",
    response_model=Token,
    responses=LOGIN_ERROR_RESPONSES,
    summary="Sign in and get an access token",
    description=(
        "OAuth2 password flow: send `username` (the account email) and `password` "
        "as form data. Returns a bearer JWT whose `sub` claim is the user id."
    ),
)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[JWTSettings, Depends(get_jwt_settings)],
) -> Token:
    try:
        user = await authenticate_user(session, form_data.username, form_data.password)
    except Exception as exc:
        logger.exception("Failed to authenticate user")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to sign in.",
        ) from exc

    if user is None:
        # One message for unknown email and wrong password avoids account enumeration.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return Token(access_token=create_access_token(user.id, settings))
