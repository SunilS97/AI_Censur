from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_censur.utils.constants import PROJECT_ROOT

BROKER_URL_SCHEMES = {"redis", "rediss", "unix"}


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


class BrokerSettings(BaseSettings):
    """Celery message-broker settings (Redis), read from `BROKER_URL`."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
    )

    # SecretStr because a Redis URL may embed a password.
    broker_url: SecretStr = Field(min_length=1)

    @field_validator("broker_url")
    @classmethod
    def validate_scheme(cls, value: SecretStr) -> SecretStr:
        if urlsplit(value.get_secret_value()).scheme not in BROKER_URL_SCHEMES:
            raise ValueError(
                "BROKER_URL must start with redis://, rediss:// or unix://"
            )
        return value


@lru_cache
def get_broker_settings() -> BrokerSettings:
    return BrokerSettings()
