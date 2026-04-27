# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""sync models

Revision ID: d9ffd7d4576b
Revises: a1b2c3d4e5f6
Create Date: 2026-03-24 01:41:26.953964

"""

from typing import Sequence

# revision identifiers, used by Alembic.
revision: str = "d9ffd7d4576b"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No schema changes.

    This revision was originally generated as a placeholder for a model-sync
    pass on 2026-03-24. The tables it would have created (email_suppressions,
    watchlists, crypto_payments, api_keys, aml_alerts, broker_connections,
    chargebacks, tax_reports, reconciliation_records) were subsequently added
    by later migrations in the chain:

      e1f2a3b4c5d6 — email_suppressions
      f1a2b3c4d5e6 — watchlists
      b2c3d4e5f6a7 — crypto_payments, outbox_events, config_store
      c1d2e3f4a5b6 — api_keys, aml_alerts, broker_connections,
                     chargebacks, tax_reports, reconciliation_records

    Filling in the body here would double-create those tables on databases
    that have already run the later migrations. The revision is kept as a
    no-op to preserve the migration chain integrity.
    """


def downgrade() -> None:
    """No schema changes — see upgrade() docstring."""
