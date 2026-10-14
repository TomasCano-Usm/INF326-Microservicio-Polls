"""Record intentionally skipped Messages deliveries.

Revision ID: 0002_messages_skipped
Revises: 0001_initial
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_messages_skipped"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_message_deliveries_status",
        "message_deliveries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_message_deliveries_status",
        "message_deliveries",
        "status IN ('pending', 'processing', 'sent', 'failed', 'skipped')",
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE message_deliveries SET status = 'sent' WHERE status = 'skipped'")
    )
    op.drop_constraint(
        "ck_message_deliveries_status",
        "message_deliveries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_message_deliveries_status",
        "message_deliveries",
        "status IN ('pending', 'processing', 'sent', 'failed')",
    )
