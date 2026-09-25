# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""``scripts/crypto_address_collision_report.py`` — read-only reconciliation
report for MASTER_OUTSTANDING §A11 owner action (a).

Until 2026-09-25 every BTC deposit address request returned the same address
(HD index 0), and ETH / USDT_ERC20 could reuse indices across workers and
collide with each other (same derivation path from one mnemonic). The owner
action recorded in §A11 is: "Every BTC payment already issued shares one
address, and early ETH/USDT payments may share addresses. Reconcile deposits
to those addresses by amount and time." This script is the read-only report
that surfaces which stored payments/orders need that manual reconciliation —
it credits nothing and looks up nothing on-chain.

Payments are recorded in two places, and both must be read:

* ``crypto_payments`` (a real table, ``database/models.py::CryptoPayment``) —
  written by ``api/payments.py::generate_deposit_address``.
* the billing order store — before 2026-09-24 ``api/billing.py::create_crypto_order``
  wrote its orders via ``api.db_store.db_set``, a JSON blob under
  ``crypto_order:{order_id}`` in the ``configurations`` table, not a dedicated
  table.

This suite builds its schema with ``alembic upgrade head`` (not
``Base.metadata.create_all``), the same pattern as
``tests/unit/test_outbox_and_crypto_payments_autoincrement_migration.py``,
because a schema built only by migrations is what every real deployment has.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Configuration, CryptoPayment

pytestmark = [pytest.mark.unit, pytest.mark.slow]

UTC = timezone.utc
REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


@pytest.fixture()
def migrated_db(tmp_path):
    """A real SQLite database built only by the migrations, seeded via a
    normal (writable) engine. Yields the sqlite ``DATABASE_URL`` string."""
    db = tmp_path / "recon.db"
    url = f"sqlite:///{db}"
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        command.upgrade(cfg, "head")
    yield url


def _session(url):
    engine = create_engine(url)
    return engine, sessionmaker(bind=engine)()


def _crypto_payment(**overrides):
    now = datetime.now(UTC)
    defaults = dict(
        payment_id=f"PAY_{id(overrides)}",
        user_id="user-1",
        plan_id="pro",
        currency="BTC",
        network="BTC",
        address="addr-default",
        derivation_index=0,
        derivation_path="m/44'/0'/0'/0/0",
        amount_usd=Decimal("100.00"),
        amount_crypto=Decimal("0.00153846"),
        rate_usd=Decimal("65000.00000000"),
        status="pending",
        confirmations=0,
        confirmations_required=2,
        created_at=now,
        expires_at=now + timedelta(minutes=30),
    )
    defaults.update(overrides)
    return CryptoPayment(**defaults)


def _billing_order(order_id, **overrides):
    now = datetime.now(UTC)
    order = {
        "order_id": order_id,
        "user_id": "user-9",
        "currency": "BTC",
        "amount_usd": 100.0,
        "address": "addr-default",
        "status": "pending",
        "created_at": now.isoformat(),
        "expires_at": None,
    }
    order.update(overrides)
    return Configuration(
        environment="test",
        config_key=f"crypto_order:{order_id}",
        config_value=json.dumps(order),
        changed_by="test",
    )


def _run(url, *args):
    """Run the script as a subprocess so ``main()``'s argv handling and exit
    code are exercised exactly as an operator would invoke it."""
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "crypto_address_collision_report.py"),
            "--database-url",
            url,
            *args,
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=60,
        check=False,
    )
    return proc


def test_no_collisions_exits_zero(migrated_db):
    engine, session = _session(migrated_db)
    session.add(_crypto_payment(payment_id="PAY_A", address="addr-A"))
    session.add(_crypto_payment(payment_id="PAY_B", address="addr-B", currency="ETH", network="ETH"))
    session.commit()
    session.close()
    engine.dispose()

    proc = _run(migrated_db, "--format", "json")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    assert report["collisions"] == []
    assert report["summary"]["total_payments"] == 2
    assert report["summary"]["colliding_addresses"] == 0
    assert report["summary"]["payments_affected"] == 0


def test_two_btc_payments_same_address_detected(migrated_db):
    engine, session = _session(migrated_db)
    session.add(_crypto_payment(payment_id="PAY_1", address="shared-btc-addr"))
    session.add(_crypto_payment(payment_id="PAY_2", address="shared-btc-addr", user_id="user-2"))
    session.commit()
    session.close()
    engine.dispose()

    proc = _run(migrated_db, "--format", "json")
    assert proc.returncode == 1, proc.stderr
    report = json.loads(proc.stdout)
    assert len(report["collisions"]) == 1
    group = report["collisions"][0]
    assert group["chain"] == "BTC"
    assert group["address"] == "shared-btc-addr"
    assert group["count"] == 2
    ids = {p["id"] for p in group["payments"]}
    assert ids == {"PAY_1", "PAY_2"}
    assert report["summary"]["colliding_addresses"] == 1
    assert report["summary"]["payments_affected"] == 2

    # Also readable in text form.
    proc_text = _run(migrated_db, "--format", "text")
    assert proc_text.returncode == 1
    assert "PAY_1" in proc_text.stdout
    assert "PAY_2" in proc_text.stdout
    assert "shared-btc-addr" in proc_text.stdout


def test_eth_and_usdt_erc20_share_address_flagged(migrated_db):
    engine, session = _session(migrated_db)
    session.add(_crypto_payment(payment_id="PAY_ETH", address="0xshared", currency="ETH", network="ETH", plan_id="pro"))
    session.add(
        _crypto_payment(payment_id="PAY_USDT", address="0xshared", currency="USDT", network="ERC20", user_id="user-2")
    )
    session.commit()
    session.close()
    engine.dispose()

    proc = _run(migrated_db, "--format", "json")
    assert proc.returncode == 1, proc.stderr
    report = json.loads(proc.stdout)
    assert len(report["collisions"]) == 1
    group = report["collisions"][0]
    assert group["chain"] == "ETH"
    assert group["mixed_currency_eth_usdt_erc20"] is True

    proc_text = _run(migrated_db, "--format", "text")
    assert "ETH" in proc_text.stdout and "USDT" in proc_text.stdout
    assert "MIXED" in proc_text.stdout.upper()


def test_billing_order_shares_address_with_crypto_payment(migrated_db):
    """Both storage locations must be read: a billing order (Configuration
    table) sharing an address with a crypto_payments row is still a
    collision."""
    engine, session = _session(migrated_db)
    session.add(_crypto_payment(payment_id="PAY_TABLE", address="cross-source-addr"))
    session.add(_billing_order("ORDER_1", address="cross-source-addr"))
    session.commit()
    session.close()
    engine.dispose()

    proc = _run(migrated_db, "--format", "json")
    assert proc.returncode == 1, proc.stderr
    report = json.loads(proc.stdout)
    assert len(report["collisions"]) == 1
    ids = {p["id"] for p in report["collisions"][0]["payments"]}
    assert ids == {"PAY_TABLE", "ORDER_1"}
    sources = {p["source"] for p in report["collisions"][0]["payments"]}
    assert sources == {"crypto_payments", "billing_order"}


def test_summary_amount_totals_are_exact_decimal_strings(migrated_db):
    engine, session = _session(migrated_db)
    session.add(_crypto_payment(payment_id="PAY_X", address="addr-x", amount_usd=Decimal("100.10")))
    session.add(
        _crypto_payment(payment_id="PAY_Y", address="addr-y", currency="ETH", network="ETH", amount_usd=Decimal("0.20"))
    )
    session.commit()
    session.close()
    engine.dispose()

    proc = _run(migrated_db, "--format", "json")
    assert proc.returncode == 0, proc.stderr
    report = json.loads(proc.stdout)
    # 100.10 + 0.20 must be exact — a float would print 100.29999999999998.
    assert report["summary"]["total_amount_usd"] == "100.30"


def test_exit_code_two_on_unreachable_database(tmp_path):
    missing = tmp_path / "does_not_exist" / "nope.db"
    proc = _run(f"sqlite:///{missing}", "--format", "json")
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_help_text_warns_no_autocrediting_and_no_network_calls():
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "crypto_address_collision_report.py"), "--help"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0
    help_text = proc.stdout.lower()
    assert "manual" in help_text
    assert "no automatic crediting" in help_text or "not credit" in help_text
    assert "on-chain" in help_text or "network" in help_text


def test_read_only_engine_rejects_a_write(migrated_db):
    """The script's own connection must not be able to write. A raw INSERT
    attempted through it must fail rather than succeed."""
    from scripts.crypto_address_collision_report import open_read_only_engine

    engine = open_read_only_engine(migrated_db)
    try:
        with pytest.raises(sa.exc.OperationalError):
            with engine.connect() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO configurations (environment, config_key, config_value) "
                        "VALUES ('test', 'should-not-write', '{}')"
                    )
                )
                conn.commit()
    finally:
        engine.dispose()

    # And prove the row genuinely never landed, via a normal writable engine.
    check_engine = create_engine(migrated_db)
    with check_engine.connect() as conn:
        row = conn.execute(
            sa.text("SELECT COUNT(*) FROM configurations WHERE config_key = 'should-not-write'")
        ).scalar()
    check_engine.dispose()
    assert row == 0
