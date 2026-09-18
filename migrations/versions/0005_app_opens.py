"""Count Mini App opens.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Counted rather than inferred from taps and answers: the number worth
    # having is how many people opened a thing and then did nothing, and an
    # inferred count cannot see that by construction.
    for column in ("reader_opens", "review_opens"):
        op.add_column(
            "usage_days",
            sa.Column(column, sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_column("usage_days", "review_opens")
    op.drop_column("usage_days", "reader_opens")
