from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_censur.utils.constants import PROJECT_ROOT


class JWTSettings(BaseSettings):
    """Token-signing settings, read from the environment or `.env`."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="JWT_",
        extra="ignore",
    )

    secret: SecretStr = Field(min_length=1)
    # Only HMAC algorithms: this rules out "none" and key-confusion with public keys.
    algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, gt=0)


@lru_cache
def get_jwt_settings() -> JWTSettings:
    return JWTSettings()
