from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Enum
from sqlalchemy.dialects import postgresql
from sqlmodel import Field, Relationship, SQLModel


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AudioStatus(StrEnum):
    """Lifecycle of an audio record through background censoring."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SoundEffect(SQLModel, table=True):
    """A censoring sound uploaded by a user, used instead of the default beep."""

    __tablename__ = "sound_effects"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    name: str = Field(nullable=False)
    file_path: str = Field(nullable=False)
    # The user who uploaded the sound; deleting the user deletes their sounds.
    user_id: UUID = Field(
        foreign_key="users.id", ondelete="CASCADE", index=True, nullable=False
    )

    user: "User" = Relationship(back_populates="sound_effects")


class Audio(SQLModel, table=True):
    __tablename__ = "audio"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=_utc_now,
        sa_type=DateTime(timezone=True),
        # Refreshed on every UPDATE, including the worker's status changes.
        sa_column_kwargs={"onupdate": _utc_now},
        nullable=False,
    )
    name: str = Field(nullable=False)
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
    # Word-level transcript (word, start, end, score); JSONB on PostgreSQL.
    transcription: list[dict[str, Any]] | None = Field(
        default=None,
        sa_type=JSON().with_variant(postgresql.JSONB(), "postgresql"),
        nullable=True,
    )
    use_beep: bool = Field(
        default=False,
        sa_column_kwargs={"server_default": "false"},
        nullable=False,
    )
    # Extra words this user wants censored, as a PostgreSQL text[] column.
    user_list: list[str] | None = Field(
        default=None,
        sa_type=postgresql.ARRAY(postgresql.TEXT()).with_variant(JSON(), "sqlite"),
        nullable=True,
    )
    # Every audio belongs to the user who uploaded it; deleting the user deletes it.
    user_id: UUID = Field(
        foreign_key="users.id", ondelete="CASCADE", index=True, nullable=False
    )
    # Deleting a sound effect keeps the audio and falls back to the default beep.
    sound_effect_id: UUID | None = Field(
        default=None,
        foreign_key="sound_effects.id",
        ondelete="SET NULL",
        index=True,
    )

    user: "User" = Relationship(back_populates="audios")
    sound_effect: SoundEffect | None = Relationship(
        sa_relationship_kwargs={"lazy": "selectin"}
    )


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
    sound_effects: list[SoundEffect] = Relationship(
        back_populates="user",
        cascade_delete=True,
        passive_deletes=True,
        sa_relationship_kwargs={"order_by": "SoundEffect.created_at"},
    )
