"""Role-play scenarios on a conversation.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All nullable: every existing conversation is a free one, and a free
    # conversation simply has no scenario.
    op.add_column("sessions", sa.Column("scenario_key", sa.String(32), nullable=True))
    op.add_column("sessions", sa.Column("goals_done", sa.String(32), nullable=True))
    op.add_column("sessions", sa.Column("card_message_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "card_message_id")
    op.drop_column("sessions", "goals_done")
    op.drop_column("sessions", "scenario_key")
