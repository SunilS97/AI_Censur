import logging
from collections.abc import Iterator
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine
from sqlalchemy.engine import URL
from sqlmodel import Session, SQLModel, create_engine

from ai_censur.database.models import Audio  # noqa: F401  (registers the table)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection settings, read from the environment or `.env`."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="DB_",
        extra="ignore",
    )

    host: str = "localhost"
    port: int = 5432
    name: str
    user: str
    password: SecretStr

    @property
    def url(self) -> URL:
        # URL.create escapes special characters in the password safely.
        return URL.create(
            drivername="postgresql+pg8000",
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        )


def create_database_engine(settings: DatabaseSettings | None = None) -> Engine:
    settings = settings or DatabaseSettings()
    return create_engine(
        settings.url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
    )


_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_database_engine()
    return _engine


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(get_engine())
    logger.info("Database tables are ready")


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session that is closed after the request."""
    with Session(get_engine()) as session:
        yield session


def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
