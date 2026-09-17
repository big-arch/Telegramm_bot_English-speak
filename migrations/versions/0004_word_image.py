"""A picture for the review card.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable carries meaning here rather than being a concession to existing
    # rows: NULL is "nobody has looked", "" is "looked, found nothing", and a
    # URL is a URL. Collapsing the first two would re-search the archives for
    # every abstract word on every single review.
    op.add_column("words", sa.Column("image_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("words", "image_url")
