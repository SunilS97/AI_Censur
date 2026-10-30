"""sound effects and audio customization

Revision ID: 00d76ad4be03
Revises: 309901ebda07
Create Date: 2026-10-29 15:49:27.303586

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "00d76ad4be03"
down_revision: str | Sequence[str] | None = "309901ebda07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "sound_effects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("file_path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sound_effects_user_id"), "sound_effects", ["user_id"], unique=False
    )
    op.add_column(
        "audio", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)
    )
    op.add_column(
        "audio", sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False)
    )
    op.add_column(
        "audio",
        sa.Column(
            "transcription",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()), "postgresql"
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "audio",
        sa.Column("use_beep", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "audio",
        sa.Column(
            "user_list",
            postgresql.ARRAY(sa.TEXT()).with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )
    op.add_column("audio", sa.Column("sound_effect_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_audio_sound_effect_id"), "audio", ["sound_effect_id"], unique=False
    )
    op.create_foreign_key(
        "audio_sound_effect_id_fkey",
        "audio",
        "sound_effects",
        ["sound_effect_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("audio_sound_effect_id_fkey", "audio", type_="foreignkey")
    op.drop_index(op.f("ix_audio_sound_effect_id"), table_name="audio")
    op.drop_column("audio", "sound_effect_id")
    op.drop_column("audio", "user_list")
    op.drop_column("audio", "use_beep")
    op.drop_column("audio", "transcription")
    op.drop_column("audio", "name")
    op.drop_column("audio", "updated_at")
    op.drop_index(op.f("ix_sound_effects_user_id"), table_name="sound_effects")
    op.drop_table("sound_effects")
