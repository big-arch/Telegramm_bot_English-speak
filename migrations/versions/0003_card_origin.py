"""Record how a card got into the deck.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-17

The reader paints words the learner tapped. Without this column it could only
ask "is this word in the deck", which is also true of the words the assessor
collects by itself — so opening the reader lit up words nobody had chosen, and
was reported, fairly, as the text underlining itself.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Every existing card predates the reader, so "conversation" is not a
    # default so much as a fact about all of them. Filled in for existing rows
    # before the NOT NULL goes on, which is the order a populated table needs.
    op.add_column(
        "user_cards",
        sa.Column(
            "origin",
            sa.String(16),
            nullable=False,
            server_default="conversation",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_cards", "origin")
