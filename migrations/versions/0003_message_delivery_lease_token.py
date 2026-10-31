"""Fence stale message delivery workers.

Revision ID: 0003_delivery_lease_token
Revises: 0002_messages_skipped
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_delivery_lease_token"
down_revision = "0002_messages_skipped"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "message_deliveries",
        sa.Column("lease_token", sa.Uuid(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("message_deliveries", "lease_token")
