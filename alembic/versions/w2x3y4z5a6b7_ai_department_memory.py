"""ai_department_memory — spec §2's memory/, which had no table

Departments declared a `memory` field typed `tuple[str, ...]` — labels with no
store behind them. This is the store: working memory per department, scoped so
one department cannot read another's, and capped in the application layer so it
does not become an archive. The permanent record stays `audit_log`, which has
its own retention and hash chain.

Revision ID: w2x3y4z5a6b7
Revises: v1w2x3y4z5a6
Create Date: 2026-09-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "w2x3y4z5a6b7"
down_revision = "v1w2x3y4z5a6"
branch_labels = None
depends_on = None

_TABLE = "ai_department_memory"


def _has_table(name: str) -> bool:
    """Idempotent guard, matching the convention in the preceding migrations."""
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    if _has_table(_TABLE):
        return

    op.create_table(
        _TABLE,
        # BigInteger on PostgreSQL, Integer on SQLite so it aliases rowid. A
        # plain Integer would cap an append-heavy table at 2^31 rows on
        # PostgreSQL, which is the mistake audit_log's own comment records.
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer, "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("department", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        # JSON as text, so SQLite (tests, dev) and PostgreSQL (production)
        # behave identically. Reads are "most recent N of this kind", never
        # queries inside the value.
        sa.Column("value_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(f"ix_{_TABLE}_department", _TABLE, ["department"])
    op.create_index(f"ix_{_TABLE}_kind", _TABLE, ["kind"])
    op.create_index(f"ix_{_TABLE}_created_at", _TABLE, ["created_at"])
    # The composite index every read actually uses: one department, optionally
    # one kind, newest first.
    op.create_index("ix_ai_dept_memory_scope", _TABLE, ["department", "kind", "created_at"])


def downgrade() -> None:
    if not _has_table(_TABLE):
        return
    op.drop_index("ix_ai_dept_memory_scope", table_name=_TABLE)
    op.drop_index(f"ix_{_TABLE}_created_at", table_name=_TABLE)
    op.drop_index(f"ix_{_TABLE}_kind", table_name=_TABLE)
    op.drop_index(f"ix_{_TABLE}_department", table_name=_TABLE)
    op.drop_table(_TABLE)
