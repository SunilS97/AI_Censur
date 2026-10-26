from datetime import UTC, datetime
from enum import StrEnum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum
from sqlmodel import Field, Relationship, SQLModel


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AudioStatus(StrEnum):
    """Lifecycle of an audio record through background censoring."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Audio(SQLModel, table=True):
    __tablename__ = "audio"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    uncensored_file_path: str = Field(nullable=False)
    # Stays empty until the background task has produced the censored file.
    censored_file_path: str | None = Field(default=None, nullable=True)
    status: AudioStatus = Field(
        default=AudioStatus.PENDING,
        # Store the lowercase values ("pending"), not the member names.
        sa_type=Enum(
            AudioStatus,
            name="audio_status",
            values_callable=lambda enum: [member.value for member in enum],
        ),
        sa_column_kwargs={"server_default": AudioStatus.PENDING.value},
        nullable=False,
    )
    # Nullable until /censor requires authentication and always has an owner.
    user_id: UUID | None = Field(
        default=None, foreign_key="users.id", ondelete="CASCADE", index=True
    )

    user: Optional["User"] = Relationship(back_populates="audios")


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    email: str = Field(unique=True, index=True, nullable=False, max_length=320)
    password_hash: str = Field(nullable=False)

    audios: list[Audio] = Relationship(
        back_populates="user",
        cascade_delete=True,
        passive_deletes=True,
    )
