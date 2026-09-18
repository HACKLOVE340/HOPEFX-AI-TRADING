# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""tick_data.quality defaults to 'unknown', not 'good'

Revision ID: u1v2w3x4y5z6
Revises: t1u2v3w4x5y6
Create Date: 2026-09-06

`tick_data.quality` defaulted to `"good"` and `confidence` to `1.0`, so every
row inserted without an assessment carried a maximum-confidence grade nobody
computed. `data_layer/quality/engine.py::DataQualityEngine` exists to produce
exactly those two fields; the defaults asserted its conclusion without running
it (audit TODO item 5, last module).

`TickQuality` gained an `UNKNOWN` member and every default site moved to it —
the ORM column here, `data_layer/types.py::GoldTick`, the orchestrator's two
cache reads, the tick store and the repository signature.

**Behaviour today is unchanged, deliberately.** Every downstream filter tests
`quality != TickQuality.REJECTED`, so `"unknown"` passes exactly where `"good"`
did and no tick that flows now stops flowing. This is about the record being
truthful, which is the prerequisite for any future gate — a gate built on a
field that always says "good" gates nothing.

**Existing rows are not rewritten.** A row already stored as `"good"` may have
been genuinely assessed, and this migration cannot tell which were. Relabelling
them `"unknown"` would destroy real measurements to fix a default; leaving them
keeps every measurement that was real and only changes what happens from here.

Whether an unknown-quality tick may reach the trading path is a policy question
for the owner and is deliberately not decided here. The point of the member is
that the question is now expressible.
"""

import sqlalchemy as sa
from alembic import op

revision = "u1v2w3x4y5z6"
down_revision = "t1u2v3w4x5y6"
branch_labels = None
depends_on = None

_TABLE = "tick_data"


def _has_quality_column() -> bool:
    """True only when there is something here to alter.

    `tick_data` is one of the tables that exists only via `create_all()` (audit
    F218, TODO item 3), so a migrated database may hold an older shape of it —
    or the column may not be there at all. Altering a column that does not exist
    aborts the whole migration, which would block every later one over a table
    whose default `create_all()` will set correctly from the model anyway.
    """
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return False
    return any(column["name"] == "quality" for column in inspector.get_columns(_TABLE))


def upgrade() -> None:
    if not _has_quality_column():
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column(
            "quality",
            existing_type=sa.String(20),
            existing_nullable=True,
            server_default="unknown",
        )


def downgrade() -> None:
    if not _has_quality_column():
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column(
            "quality",
            existing_type=sa.String(20),
            existing_nullable=True,
            server_default="good",
        )
