"""remember photos the learner sends

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable on purpose: every existing turn predates photos, and adding a
    # NOT NULL column to a populated table fails.
    op.add_column("turns", sa.Column("image_file_id", sa.String(160), nullable=True))


def downgrade() -> None:
    op.drop_column("turns", "image_file_id")
