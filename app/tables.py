from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime


JSONDocument = JSON().with_variant(JSONB(), "postgresql")


class Poll(Base):
    __tablename__ = "polls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_announcement', 'open', 'closed', 'creation_failed')",
            name="ck_polls_status",
        ),
        CheckConstraint("duration_minutes BETWEEN 1 AND 1440", name="ck_polls_duration"),
        UniqueConstraint("author_id", "idempotency_key", name="uq_polls_author_idempotency"),
        Index(
            "ix_polls_due_open",
            "closes_at",
            postgresql_where=text("status = 'open'"),
            sqlite_where=text("status = 'open'"),
        ),
    )

    poll_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_announcement")
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    closes_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    creation_error_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creation_error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    options: Mapped[list["PollOption"]] = relationship(
        back_populates="poll",
        cascade="all, delete-orphan",
        order_by="PollOption.position",
        lazy="selectin",
    )


class PollOption(Base):
    __tablename__ = "poll_options"
    __table_args__ = (
        UniqueConstraint("poll_id", "position", name="uq_poll_options_position"),
        UniqueConstraint("poll_id", "option_id", name="uq_poll_options_poll_option"),
        UniqueConstraint("poll_id", "normalized_text", name="uq_poll_options_text"),
        CheckConstraint("position BETWEEN 0 AND 9", name="ck_poll_options_position"),
    )

    option_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    poll_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("polls.poll_id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)

    poll: Mapped[Poll] = relationship(back_populates="options")


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["poll_id", "option_id"],
            ["poll_options.poll_id", "poll_options.option_id"],
            name="fk_votes_poll_option",
            ondelete="CASCADE",
        ),
        Index("ix_votes_poll_option", "poll_id", "option_id"),
    )

    poll_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    voter_id: Mapped[str] = mapped_column(Text, primary_key=True)
    option_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    cast_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class MessageDelivery(Base):
    __tablename__ = "message_deliveries"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('announcement', 'final_results')",
            name="ck_message_deliveries_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'failed', 'skipped')",
            name="ck_message_deliveries_status",
        ),
        Index(
            "ix_message_deliveries_ready",
            "next_attempt_at",
            postgresql_where=text("status IN ('pending', 'processing')"),
            sqlite_where=text("status IN ('pending', 'processing')"),
        ),
        UniqueConstraint("poll_id", "kind", name="uq_message_deliveries_poll_kind"),
    )

    delivery_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    poll_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("polls.poll_id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_events_ready",
            "next_attempt_at",
            postgresql_where=text("published_at IS NULL"),
            sqlite_where=text("published_at IS NULL"),
        ),
    )

    event_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    poll_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("polls.poll_id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONDocument, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
