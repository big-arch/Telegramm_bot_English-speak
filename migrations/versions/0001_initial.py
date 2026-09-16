"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(32)),
        sa.Column("first_name", sa.String(64)),
        sa.Column("language_code", sa.String(8)),
        sa.Column("productive_level", sa.String(2), nullable=False),
        sa.Column("receptive_level", sa.String(2), nullable=False),
        sa.Column("level_score", sa.Float(), nullable=False),
        sa.Column("persona_key", sa.String(16), nullable=False),
        sa.Column("correction_style", sa.String(10), nullable=False),
        sa.Column("goal", sa.String(32)),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("reminder_hour", sa.SmallInteger()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("blocked_at", TS),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", TS),
        sa.Column("memory_summary", sa.Text()),
    )
    op.create_index("ix_users_tg_id", "users", ["tg_id"], unique=True)

    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(48), nullable=False),
        sa.Column("title_en", sa.String(96), nullable=False),
        sa.Column("title_ru", sa.String(96), nullable=False),
        sa.Column("emoji", sa.String(8), nullable=False),
        sa.Column("cefr_min", sa.String(2), nullable=False),
        sa.Column("cefr_max", sa.String(2), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("opening_line", sa.Text(), nullable=False),
        sa.Column("goal_prompt", sa.Text(), nullable=False),
        sa.Column("target_lexis", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_topics_slug", "topics", ["slug"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id", ondelete="SET NULL")),
        sa.Column("persona_key", sa.String(16), nullable=False),
        sa.Column("started_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", TS),
        sa.Column("opening_line", sa.Text()),
        sa.Column("turn_count", sa.Integer(), nullable=False),
        sa.Column("voice_turn_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("accuracy", sa.Float()),
        sa.Column("words_per_minute", sa.Float()),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_user_started", "sessions", ["user_id", "started_at"])

    op.create_table(
        "turns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("modality", sa.String(8), nullable=False),
        sa.Column("user_text", sa.Text(), nullable=False),
        sa.Column("assistant_text", sa.Text(), nullable=False),
        sa.Column("audio_seconds", sa.Float()),
        sa.Column("word_count", sa.Integer()),
        sa.Column("words_per_minute", sa.Float()),
        sa.Column("articulation_wpm", sa.Float()),
        sa.Column("pause_ratio", sa.Float()),
        sa.Column("mid_clause_pauses", sa.Integer()),
        sa.Column("mean_run_words", sa.Float()),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("estimated_level", sa.String(2)),
        sa.Column("lexical_range", sa.SmallInteger()),
        sa.Column("grammatical_range", sa.SmallInteger()),
        sa.Column("accuracy_score", sa.SmallInteger()),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_turns_session_id", "turns", ["session_id"])
    op.create_index("ix_turns_user_id", "turns", ["user_id"])
    op.create_index("ix_turns_user_created", "turns", ["user_id", "created_at"])

    op.create_table(
        "error_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("turn_id", sa.Integer(), sa.ForeignKey("turns.id", ondelete="CASCADE")),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("severity", sa.String(12), nullable=False),
        sa.Column("original_span", sa.Text(), nullable=False),
        sa.Column("correction", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text()),
        sa.Column("surfaced_at", TS),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_error_records_user_id", "error_records", ["user_id"])
    op.create_index("ix_error_records_category", "error_records", ["category"])
    op.create_index(
        "ix_errors_user_cat_time", "error_records", ["user_id", "category", "created_at"]
    )

    op.create_table(
        "words",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lemma", sa.String(64), nullable=False),
        sa.Column("pos", sa.String(16), nullable=False),
        sa.Column("cefr", sa.String(2), nullable=False),
        sa.Column("translation_ru", sa.String(128)),
        sa.Column("definition_en", sa.Text()),
        sa.Column("example_en", sa.Text()),
        sa.Column("ipa", sa.String(64)),
        sa.Column("audio_file_id", sa.String(160)),
        sa.UniqueConstraint("lemma", "pos", name="uq_word_lemma_pos"),
    )
    op.create_index("ix_words_lemma", "words", ["lemma"])
    op.create_index("ix_words_cefr", "words", ["cefr"])

    op.create_table(
        "user_cards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "word_id",
            sa.Integer(),
            sa.ForeignKey("words.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("due_at", TS, nullable=False),
        sa.Column("interval_days", sa.Integer(), nullable=False),
        sa.Column("ease", sa.Float(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("lapses", sa.Integer(), nullable=False),
        sa.Column("last_reviewed_at", TS),
        sa.Column(
            "source_session_id", sa.Integer(), sa.ForeignKey("sessions.id", ondelete="SET NULL")
        ),
        sa.UniqueConstraint("user_id", "word_id", name="uq_user_word"),
    )
    op.create_index("ix_user_cards_user_id", "user_cards", ["user_id"])
    op.create_index("ix_user_cards_due_at", "user_cards", ["due_at"])
    # The hottest query in the product: the due queue.
    op.create_index("ix_cards_due_queue", "user_cards", ["user_id", "state", "due_at"])

    op.create_table(
        "review_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "card_id",
            sa.Integer(),
            sa.ForeignKey("user_cards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("grade", sa.SmallInteger(), nullable=False),
        sa.Column("elapsed_days", sa.Float(), nullable=False),
        sa.Column("interval_before", sa.Integer(), nullable=False),
        sa.Column("ease_before", sa.Float(), nullable=False),
        sa.Column("response_ms", sa.Integer()),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_review_log_user_id", "review_log", ["user_id"])

    op.create_table(
        "audio_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("file_id", sa.String(160), nullable=False),
        sa.Column("voice_key", sa.String(48), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audio_cache_content_hash", "audio_cache", ["content_hash"], unique=True)

    op.create_table(
        "usage_days",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day", sa.String(10), nullable=False),
        sa.Column("voice_turns", sa.Integer(), nullable=False),
        sa.Column("text_turns", sa.Integer(), nullable=False),
        sa.Column("audio_seconds_in", sa.Float(), nullable=False),
        sa.Column("tts_characters", sa.Integer(), nullable=False),
        sa.Column("llm_input_tokens", sa.Integer(), nullable=False),
        sa.Column("llm_output_tokens", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "day", name="uq_usage_user_day"),
    )
    op.create_index("ix_usage_days_user_id", "usage_days", ["user_id"])


def downgrade() -> None:
    for table in (
        "usage_days",
        "audio_cache",
        "review_log",
        "user_cards",
        "words",
        "error_records",
        "turns",
        "sessions",
        "topics",
        "users",
    ):
        op.drop_table(table)
