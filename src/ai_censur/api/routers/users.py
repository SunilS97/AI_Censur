import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ai_censur.api.schemas import SIGNUP_ERROR_RESPONSES, UserCreate, UserRead
from ai_censur.database.crud import add_user
from ai_censur.database.exceptions import EmailAlreadyRegisteredError
from ai_censur.database.models import User
from ai_censur.database.session import get_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=UserRead,
    responses=SIGNUP_ERROR_RESPONSES,
    summary="Register a new user",
    description=(
        "Create an account from an email and a password. The password is hashed "
        "with Argon2 and is never stored or returned in plain text."
    ),
)
async def signup(
    user_in: UserCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    try:
        return await add_user(
            session, user_in.email, user_in.password.get_secret_value()
        )
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        ) from exc
    except Exception as exc:
        logger.exception("Failed to create user")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create the account.",
        ) from exc
