"""support_tickets / support_messages — the desk had nowhere to put a ticket

`support.triage` decided who should answer a customer and whether a human must,
then forgot: nothing persisted the conversation, nothing collected escalations
for a person to work, and nothing stopped the AI closing what it had escalated.

Two tables. `support_tickets` carries the triage decision forward —
`needs_human` is what `support.tickets.TicketStore` refuses an AI resolution
on, not a display flag. `first_response_at` is nullable and has **no default**:
stamping it at creation would report a desk answering every ticket instantly.

Revision ID: x3y4z5a6b7c8
Revises: w2x3y4z5a6b7
Create Date: 2026-09-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "x3y4z5a6b7c8"
down_revision = "w2x3y4z5a6b7"
branch_labels = None
depends_on = None

_TICKETS = "support_tickets"
_MESSAGES = "support_messages"


def _has_table(name: str) -> bool:
    """Idempotent guard, matching the convention in the preceding migrations."""
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def _pk() -> sa.types.TypeEngine:
    """BigInteger on PostgreSQL, Integer on SQLite so it aliases rowid.

    A plain Integer caps an append-heavy table at 2^31 rows on PostgreSQL —
    the mistake `audit_log`'s own comment records.
    """
    return sa.BigInteger().with_variant(sa.Integer, "sqlite")


def upgrade() -> None:
    if not _has_table(_TICKETS):
        op.create_table(
            _TICKETS,
            sa.Column("id", _pk(), primary_key=True, autoincrement=True),
            sa.Column("ticket_id", sa.String(length=40), nullable=False, unique=True),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("subject", sa.String(length=200), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
            sa.Column("category", sa.String(length=48), nullable=True),
            sa.Column("department", sa.String(length=48), nullable=True),
            sa.Column("needs_human", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("escalation_reason", sa.Text(), nullable=True),
            sa.Column("matched_on", sa.String(length=200), nullable=True),
            sa.Column("assigned_operator_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            # No default, deliberately: NULL means nothing has responded yet.
            sa.Column("first_response_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
        )
        op.create_index(f"ix_{_TICKETS}_ticket_id", _TICKETS, ["ticket_id"], unique=True)
        op.create_index(f"ix_{_TICKETS}_user_id", _TICKETS, ["user_id"])
        op.create_index(f"ix_{_TICKETS}_status", _TICKETS, ["status"])
        op.create_index(f"ix_{_TICKETS}_department", _TICKETS, ["department"])
        op.create_index(f"ix_{_TICKETS}_needs_human", _TICKETS, ["needs_human"])
        op.create_index(f"ix_{_TICKETS}_assigned_operator_id", _TICKETS, ["assigned_operator_id"])
        op.create_index(f"ix_{_TICKETS}_created_at", _TICKETS, ["created_at"])
        # The operator queue's own index: waiting tickets, oldest first.
        op.create_index("ix_support_queue", _TICKETS, ["needs_human", "status", "created_at"])

    if not _has_table(_MESSAGES):
        op.create_table(
            _MESSAGES,
            sa.Column("id", _pk(), primary_key=True, autoincrement=True),
            sa.Column("ticket_id", sa.String(length=40), nullable=False),
            sa.Column("author_kind", sa.String(length=16), nullable=False),
            sa.Column("author_id", sa.String(length=64), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(f"ix_{_MESSAGES}_ticket_id", _MESSAGES, ["ticket_id"])
        op.create_index(f"ix_{_MESSAGES}_created_at", _MESSAGES, ["created_at"])
        # The thread read: one ticket, in order.
        op.create_index("ix_support_thread", _MESSAGES, ["ticket_id", "created_at"])


def downgrade() -> None:
    if _has_table(_MESSAGES):
        op.drop_index("ix_support_thread", table_name=_MESSAGES)
        op.drop_index(f"ix_{_MESSAGES}_created_at", table_name=_MESSAGES)
        op.drop_index(f"ix_{_MESSAGES}_ticket_id", table_name=_MESSAGES)
        op.drop_table(_MESSAGES)

    if _has_table(_TICKETS):
        op.drop_index("ix_support_queue", table_name=_TICKETS)
        op.drop_index(f"ix_{_TICKETS}_created_at", table_name=_TICKETS)
        op.drop_index(f"ix_{_TICKETS}_assigned_operator_id", table_name=_TICKETS)
        op.drop_index(f"ix_{_TICKETS}_needs_human", table_name=_TICKETS)
        op.drop_index(f"ix_{_TICKETS}_department", table_name=_TICKETS)
        op.drop_index(f"ix_{_TICKETS}_status", table_name=_TICKETS)
        op.drop_index(f"ix_{_TICKETS}_user_id", table_name=_TICKETS)
        op.drop_index(f"ix_{_TICKETS}_ticket_id", table_name=_TICKETS)
        op.drop_table(_TICKETS)
