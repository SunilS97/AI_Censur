"""audio user id required

Revision ID: 309901ebda07
Revises: d45b1fe91113
Create Date: 2026-10-26 16:06:33.085684

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "309901ebda07"
down_revision: str | Sequence[str] | None = "d45b1fe91113"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    orphans = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM audio WHERE user_id IS NULL"))
        .scalar_one()
    )
    if orphans:
        raise RuntimeError(
            f"{orphans} audio row(s) have no user_id. Assign an owner or delete "
            "them before making audio.user_id required."
        )
    op.alter_column("audio", "user_id", existing_type=sa.UUID(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("audio", "user_id", existing_type=sa.UUID(), nullable=True)
