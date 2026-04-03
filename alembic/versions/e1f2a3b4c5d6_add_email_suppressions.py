# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""add email_suppressions table

Revision ID: e1f2a3b4c5d6
Revises: d9ffd7d4576b
Create Date: 2025-01-01 00:00:00.000000

Stores addresses suppressed due to bounce, spam_report, or unsubscribe events
received from the SendGrid Event Webhook (POST /api/email/webhook).
EmailChannel.send() checks this table before every dispatch.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d9ffd7d4576b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_suppressions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column(
            "reason",
            sa.String(64),
            nullable=False,
            comment="bounce | spam_report | unsubscribe | group_unsubscribe",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),  # pylint: disable=not-callable
        ),
    )
    op.create_index(
        "ix_email_suppressions_email",
        "email_suppressions",
        ["email"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_email_suppressions_email", table_name="email_suppressions")
    op.drop_table("email_suppressions")
