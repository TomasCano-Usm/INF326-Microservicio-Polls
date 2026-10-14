"""Initial Polls schema.

Revision ID: 0001_initial
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "polls",
        sa.Column("poll_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("creation_error_status", sa.Integer(), nullable=True),
        sa.Column("creation_error_detail", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending_announcement', 'open', 'closed', 'creation_failed')",
            name="ck_polls_status",
        ),
        sa.CheckConstraint("duration_minutes BETWEEN 1 AND 1440", name="ck_polls_duration"),
        sa.UniqueConstraint("author_id", "idempotency_key", name="uq_polls_author_idempotency"),
    )
    op.create_index(
        "ix_polls_due_open",
        "polls",
        ["closes_at"],
        postgresql_where=sa.text("status = 'open'"),
        sqlite_where=sa.text("status = 'open'"),
    )

    op.create_table(
        "poll_options",
        sa.Column("option_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "poll_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("polls.poll_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.CheckConstraint("position BETWEEN 0 AND 9", name="ck_poll_options_position"),
        sa.UniqueConstraint("poll_id", "position", name="uq_poll_options_position"),
        sa.UniqueConstraint("poll_id", "option_id", name="uq_poll_options_poll_option"),
        sa.UniqueConstraint("poll_id", "normalized_text", name="uq_poll_options_text"),
    )

    op.create_table(
        "votes",
        sa.Column("poll_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("voter_id", sa.Text(), primary_key=True),
        sa.Column("option_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("cast_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["poll_id", "option_id"],
            ["poll_options.poll_id", "poll_options.option_id"],
            name="fk_votes_poll_option",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_votes_poll_option", "votes", ["poll_id", "option_id"])

    op.create_table(
        "message_deliveries",
        sa.Column("delivery_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "poll_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("polls.poll_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('announcement', 'final_results')",
            name="ck_message_deliveries_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'failed')",
            name="ck_message_deliveries_status",
        ),
        sa.UniqueConstraint("poll_id", "kind", name="uq_message_deliveries_poll_kind"),
    )
    op.create_index(
        "ix_message_deliveries_ready",
        "message_deliveries",
        ["next_attempt_at"],
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
        sqlite_where=sa.text("status IN ('pending', 'processing')"),
    )

    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "poll_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("polls.poll_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_outbox_events_ready",
        "outbox_events",
        ["next_attempt_at"],
        postgresql_where=sa.text("published_at IS NULL"),
        sqlite_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_ready", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_message_deliveries_ready", table_name="message_deliveries")
    op.drop_table("message_deliveries")
    op.drop_index("ix_votes_poll_option", table_name="votes")
    op.drop_table("votes")
    op.drop_table("poll_options")
    op.drop_index("ix_polls_due_open", table_name="polls")
    op.drop_table("polls")
