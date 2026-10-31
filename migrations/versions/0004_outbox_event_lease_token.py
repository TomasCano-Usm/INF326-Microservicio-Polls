"""Fence stale transactional outbox workers.

Revision ID: 0004_outbox_lease_token
Revises: 0003_delivery_lease_token
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_outbox_lease_token"
down_revision = "0003_delivery_lease_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("lease_token", sa.Uuid(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outbox_events", "lease_token")
