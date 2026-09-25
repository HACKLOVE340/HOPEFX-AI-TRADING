# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""crypto HD derivation indices come from PostgreSQL sequences, one per chain

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-09-25

``payments/crypto/address_generator.py`` reserved every deposit-address index
from a counter FILE under an exclusive OS lock. That is shared by the workers
of one host and by nothing else, and production runs several hosts:
``k8s/k8s-deployment.yaml`` has ``replicas: 3`` with an HPA to 12, each with
``API_WORKERS=4`` (``k8s/k8s-configmap.yaml``), and ``HOPEFX_CRYPTO_COUNTER_PATH``
is set by no manifest -- so every pod counted from its own container
filesystem, and two pods could issue one address to two payments
(MASTER_OUTSTANDING §A11, owner item (b)).

On PostgreSQL this revision creates one sequence per derivation chain, which
the runtime then uses instead of the file -- selected by the dialect of the
payments database, not by a flag:

  crypto_hd_index_btc    BTC          m/84'/0'/0'/0/{i}
  crypto_hd_index_eth    ETH, USDT_ERC20 (one chain: same mnemonic, same path)
  crypto_hd_index_trc20  USDT_TRC20   m/44'/195'/0'/0/{i}

Each starts PAST every index already issued that this database or host can
see: the largest ``crypto_payments.derivation_index`` on the chain's path, the
largest index recorded on billing's crypto orders (``configurations`` rows
``crypto_order:*`` / ``crypto_orders:*``), and the file counter's next value if
the file exists on the host running the migration. An unreadable counter file
stops the migration rather than being treated as empty.

**Multi-host operators:** a counter file on ANOTHER host is invisible here, and
billing orders issued before this revision recorded no index. Before upgrading,
copy the largest counter file from every host to this one (or point
``HOPEFX_CRYPTO_COUNTER_PATH`` at a file holding the per-key maximum).

The sequences are ``MINVALUE 0 MAXVALUE 2147483647 NO CYCLE``: a cycling
sequence would re-issue index 0, and 2**31 onwards are hardened BIP32 indices.
``nextval`` is never rolled back, so an index drawn for a request that later
fails is skipped, never reused.

On SQLite (and anything that is not PostgreSQL) this revision does nothing: the
file lock remains the index source there, and SQLite is single-host.

Downgrade drops the sequences after logging where each stood. The runtime then
refuses to issue on PostgreSQL until the revision is re-applied; re-applying
re-seeds from the records above.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "d9e0f1a2b3c4"  # pragma: allowlist secret
down_revision = "c8d9e0f1a2b3"  # pragma: allowlist secret
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

# sequence -> (derivation path prefix, counter-file keys on that chain).
# A copy of payments/crypto/address_generator.py::_SEQUENCE/_PATHS/_CHAIN, held
# equal by tests/unit/test_crypto_hd_index_comes_from_the_database_on_postgres.py.
# Copied rather than imported so this revision does not change when the app does.
SEQUENCES: dict[str, tuple[str, tuple[str, ...]]] = {
    "crypto_hd_index_btc": ("m/84'/0'/0'/0/", ("BTC",)),
    "crypto_hd_index_eth": ("m/44'/60'/0'/0/", ("ETH", "USDT_ERC20")),
    "crypto_hd_index_trc20": ("m/44'/195'/0'/0/", ("USDT_TRC20",)),
}

MAX_INDEX = 2**31 - 1

_DEFAULT_COUNTER_PATH = Path(__file__).resolve().parents[2] / "data" / "crypto_counters.json"


def _sequence(name: str, start: int) -> sa.Sequence:
    return sa.Sequence(
        name,
        start=start,
        minvalue=0,
        maxvalue=MAX_INDEX,
        cycle=False,
        cache=1,
        data_type=sa.BigInteger(),
    )


def create_sequence_sql(name: str, start: int) -> sa.schema.CreateSequence:
    """The DDL for one chain's sequence (compiled per dialect by the caller)."""
    if name not in SEQUENCES:
        raise ValueError(f"unknown crypto index sequence {name!r}")
    if not 0 <= start <= MAX_INDEX:
        raise RuntimeError(f"{name} would start at {start}, outside [0, {MAX_INDEX}]")
    return sa.schema.CreateSequence(_sequence(name, start), if_not_exists=True)


def _counter_file_next() -> dict[str, int]:
    """The file counter's NEXT index per key, or {} if there is no file."""
    path = Path(os.getenv("HOPEFX_CRYPTO_COUNTER_PATH", str(_DEFAULT_COUNTER_PATH)))
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"expected a JSON object, found {type(data).__name__}")
        return {str(k): int(v) for k, v in data.items()}
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError(
            f"The crypto derivation counter at {path} is unreadable ({exc}). Refusing to seed the "
            "index sequences from an unknown starting point: that could re-issue addresses. Repair "
            "or remove the file (after recording its values) and re-run the upgrade."
        ) from exc


def _max_recorded_payment_index(bind, prefix: str) -> int | None:
    inspector = sa.inspect(bind)
    if "crypto_payments" not in set(inspector.get_table_names()):
        return None
    cols = {c["name"] for c in inspector.get_columns("crypto_payments")}
    if not {"derivation_index", "derivation_path"} <= cols:
        return None
    return bind.execute(
        sa.text(
            "SELECT MAX(derivation_index) FROM crypto_payments "
            "WHERE derivation_index IS NOT NULL AND derivation_path LIKE :prefix"
        ),
        {"prefix": prefix + "%"},
    ).scalar()


def _max_recorded_order_index(bind, prefix: str) -> int | None:
    """Billing's crypto orders live as JSON in ``configurations`` (api/db_store.py)."""
    if "configurations" not in set(sa.inspect(bind).get_table_names()):
        return None
    rows = bind.execute(
        sa.text("SELECT config_value FROM configurations WHERE config_key LIKE 'crypto_order%'")
    ).scalars()
    best: int | None = None
    for raw in rows:
        try:
            value = json.loads(raw) if raw else None
        except ValueError:
            continue
        for order in value if isinstance(value, list) else [value]:
            if not isinstance(order, dict):
                continue
            path, idx = order.get("derivation_path"), order.get("derivation_index")
            if isinstance(path, str) and path.startswith(prefix) and isinstance(idx, int):
                best = idx if best is None else max(best, idx)
    return best


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        log.info("crypto HD index sequences: %s is not PostgreSQL; the file counter stays in use.", bind.dialect.name)
        return

    file_next = _counter_file_next()
    for name, (prefix, keys) in SEQUENCES.items():
        recorded = [
            v
            for v in (_max_recorded_payment_index(bind, prefix), _max_recorded_order_index(bind, prefix))
            if v is not None
        ]
        start = max([0, *(v + 1 for v in recorded), *(file_next.get(k, 0) for k in keys)])
        op.execute(create_sequence_sql(name, start))
        # If the sequence already existed (created by hand, or a re-run), make
        # sure it is not behind what has already been issued. `name` is one of
        # the three constants above, never input.
        op.execute(
            sa.text(
                f"SELECT setval('{name}', :start, false) "  # nosec B608 - constant sequence name
                f"WHERE :start > (SELECT CASE WHEN is_called THEN last_value + 1 ELSE last_value END FROM {name})"
            ).bindparams(start=start)
        )
        log.info(
            "crypto HD index sequence %s: next index >= %d (recorded=%s, file=%s)", name, start, recorded, file_next
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    existing = set(sa.inspect(bind).get_sequence_names())
    for name in SEQUENCES:
        if name in existing:
            last = bind.execute(
                sa.text(f"SELECT last_value, is_called FROM {name}")  # nosec B608 - constant sequence name
            ).one()
            log.warning(
                "Dropping %s at last_value=%s (is_called=%s). The file counter does not know this value; "
                "seed it past this before issuing addresses from the file.",
                name,
                last[0],
                last[1],
            )
        op.execute(sa.schema.DropSequence(_sequence(name, 0), if_exists=True))
