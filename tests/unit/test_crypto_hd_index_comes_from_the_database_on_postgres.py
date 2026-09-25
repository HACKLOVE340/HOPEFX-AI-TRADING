# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""On PostgreSQL, HD derivation indices come from a database SEQUENCE.

MASTER_OUTSTANDING §A11, owner item (b): the derivation counter was a file under
an exclusive OS lock. That serialises every worker on ONE host and nothing
across hosts -- and the production manifests run the API on several:
``k8s/k8s-deployment.yaml`` has ``replicas: 3`` with an HPA to 12, and
``k8s/k8s-configmap.yaml`` sets ``API_WORKERS: "4"``, with
``HOPEFX_CRYPTO_COUNTER_PATH`` set nowhere, so each pod counted from its own
container filesystem. Two pods issue index *n* to two different payments, and
the deposits to that one address cannot be told apart.

What these tests hold:

* The index source is chosen by the **dialect of the engine the payments are
  written to**, not by a flag: PostgreSQL -> sequence, anything else -> the
  file lock.
* A sequence failure **refuses** to issue. It never falls back to the file
  counter, which would silently reintroduce the per-host counter on exactly
  the deployments that cannot use it.
* ETH and USDT_ERC20 draw from ONE sequence (they derive the same path from
  the same mnemonic); BTC and USDT_TRC20 each have their own.
* The migration seeds each sequence past every index already recorded -- in
  ``crypto_payments``, in billing's crypto orders, and in the file counter.

The tests marked ``postgres`` run against a real server: set
``HOPEFX_TEST_POSTGRES_URL`` (or a ``postgresql`` ``DATABASE_URL``, as CI does).
Each creates and drops its own database. Without one they skip; the dialect
selection, the fail-closed refusal and the migration SQL are still proven
below without a server.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.unit

pytest.importorskip("hdwallet")

TEST_MNEMONIC = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
REPO = Path(__file__).resolve().parents[2]
NEW_REVISION = "d9e0f1a2b3c4"  # pragma: allowlist secret
PREVIOUS_REVISION = "c8d9e0f1a2b3"  # pragma: allowlist secret


def _migration_module():
    [path] = (REPO / "alembic" / "versions").glob(f"{NEW_REVISION}_*.py")
    spec = importlib.util.spec_from_file_location(f"_migration_{NEW_REVISION}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def wallet_env(monkeypatch, tmp_path) -> Path:
    counter = tmp_path / "crypto_counters.json"
    monkeypatch.setenv("HOPEFX_CRYPTO_COUNTER_PATH", str(counter))
    monkeypatch.setenv("APP_ENV", "test")
    for var in ("BITCOIN_MNEMONIC", "ETHEREUM_MNEMONIC", "TRON_MNEMONIC"):
        monkeypatch.setenv(var, TEST_MNEMONIC)
    return counter


def _bind_payments_database(monkeypatch, engine) -> None:
    """Point the platform at *engine* the way startup does (``app_state``)."""
    from sqlalchemy.orm import sessionmaker

    from core.app_state import app_state

    monkeypatch.setattr(app_state, "db_engine", engine, raising=False)
    monkeypatch.setattr(app_state, "db_session_factory", sessionmaker(bind=engine), raising=False)


# ── Selection by dialect, and fail closed — no server needed ─────────────────


def test_a_sqlite_database_keeps_the_file_counter(monkeypatch, wallet_env, tmp_path):
    from payments.crypto.address_generator import AddressGenerator

    _bind_payments_database(monkeypatch, sa.create_engine(f"sqlite:///{tmp_path}/dev.db"))
    gen = AddressGenerator()
    assert [gen.reserve_index("ETH") for _ in range(3)] == [0, 1, 2]
    assert json.loads(wallet_env.read_text())["ETH"] == 3


def test_a_postgresql_database_that_cannot_answer_refuses_and_never_touches_the_file(monkeypatch, wallet_env):
    """No flag says "use the sequence": the engine is PostgreSQL, so the index
    must come from PostgreSQL. It cannot answer (nothing listens on port 1),
    so nothing is issued -- and the per-host file counter is NOT consulted as a
    fallback, which is how a multi-host deployment would silently get it back."""
    from payments.crypto.address_generator import AddressGenerator

    unreachable = sa.create_engine("postgresql+psycopg2://nobody@127.0.0.1:1/none", connect_args={"connect_timeout": 2})
    _bind_payments_database(monkeypatch, unreachable)

    with pytest.raises(RuntimeError, match="crypto_hd_index_eth"):
        AddressGenerator().reserve_index("ETH")
    assert not wallet_env.exists(), "a PostgreSQL deployment fell back to the per-host file counter"


def test_a_postgresql_database_that_cannot_answer_issues_no_address(monkeypatch, wallet_env):
    from payments.crypto.address_generator import AddressGenerator

    _bind_payments_database(
        monkeypatch,
        sa.create_engine("postgresql+psycopg2://nobody@127.0.0.1:1/none", connect_args={"connect_timeout": 2}),
    )
    with pytest.raises(RuntimeError):
        AddressGenerator().reserve_address("user-1", "BTC")
    assert not wallet_env.exists()


def test_the_chains_map_to_three_sequences_and_erc20_shares_eth():
    from payments.crypto.address_generator import _CHAIN, _SEQUENCE

    assert {c: _SEQUENCE[_CHAIN[c]] for c in _CHAIN} == {
        "BTC": "crypto_hd_index_btc",
        "ETH": "crypto_hd_index_eth",
        "USDT_ERC20": "crypto_hd_index_eth",
        "USDT_TRC20": "crypto_hd_index_trc20",
    }


def test_the_migration_and_the_runtime_name_the_same_sequences_and_paths():
    """The migration cannot import the runtime (a migration must not change
    when the application does), so the two copies are held equal here."""
    from payments.crypto.address_generator import _CHAIN, _PATHS, _SEQUENCE

    mig = _migration_module()
    assert mig.revision == NEW_REVISION
    assert mig.down_revision == PREVIOUS_REVISION
    runtime = {}
    for currency, chain in _CHAIN.items():
        prefix = _PATHS[currency].format(index="")
        runtime.setdefault(_SEQUENCE[chain], (prefix, set()))[1].add(currency)
    assert {seq: (prefix, set(keys)) for seq, (prefix, keys) in mig.SEQUENCES.items()} == runtime


def test_the_migration_sql_compiles_for_postgresql():
    """A sequence that cycles, or runs past 2**31 - 1 into hardened BIP32
    indices, would re-issue or mis-derive addresses. It must stop instead."""
    from sqlalchemy.dialects import postgresql

    mig = _migration_module()
    sql = str(mig.create_sequence_sql("crypto_hd_index_eth", 42).compile(dialect=postgresql.dialect()))
    assert "CREATE SEQUENCE IF NOT EXISTS crypto_hd_index_eth" in sql
    assert "START WITH 42" in sql
    assert "MINVALUE 0" in sql
    assert "MAXVALUE 2147483647" in sql
    assert "NO CYCLE" in sql


def test_a_sqlite_upgrade_creates_no_sequence_and_changes_nothing(tmp_path):
    """SQLite has no sequences; the file lock stays its index source, so the
    revision is a no-op there (and must not fail)."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    mig = _migration_module()
    engine = sa.create_engine(f"sqlite:///{tmp_path}/m.db")
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mig.upgrade()
            mig.downgrade()
        assert sa.inspect(conn).get_table_names() == []


# ── Against a real PostgreSQL ────────────────────────────────────────────────


def _postgres_admin_url() -> str | None:
    url = os.getenv("HOPEFX_TEST_POSTGRES_URL") or os.getenv("DATABASE_URL", "")
    if not url.startswith("postgres"):
        return None
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("postgres://", "postgresql://")


@pytest.fixture()
def pg_url():
    """A fresh, empty PostgreSQL database for one test, dropped afterwards."""
    admin_url = _postgres_admin_url()
    if admin_url is None:
        pytest.skip("no PostgreSQL: set HOPEFX_TEST_POSTGRES_URL=postgresql://user@host:port/db")
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
    try:
        with admin.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except sa.exc.OperationalError as exc:
        admin.dispose()
        pytest.skip(f"PostgreSQL at {admin_url} is not reachable: {exc}")
    name = f"hopefx_seq_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = sa.engine.make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _alembic(url: str, action: str, target: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        getattr(command, action)(cfg, target)


def _schema_at_previous_head(url: str) -> sa.Engine:
    """The tables this revision reads, at the revision before it.

    The full migration chain cannot be replayed on PostgreSQL today:
    ``x3y4z5a6b7c8`` declares ``server_default=sa.text("0")`` on a BOOLEAN
    column, which PostgreSQL rejects. That is a separate defect; here the two
    tables are built from the models and the database is stamped at the
    previous head, and then the REAL alembic upgrade/downgrade of this revision
    runs against it.
    """
    from database.models import Configuration, CryptoPayment

    engine = sa.create_engine(url)
    CryptoPayment.__table__.create(engine)
    Configuration.__table__.create(engine)
    _alembic(url, "stamp", PREVIOUS_REVISION)
    return engine


def _payment(engine, *, currency: str, network: str, index: int | None, path: str | None) -> None:
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO crypto_payments (payment_id, user_id, plan_id, currency, network, address, "
                "derivation_index, derivation_path, amount_usd, amount_crypto, rate_usd, status, confirmations, "
                "confirmations_required, created_at, expires_at, updated_at) VALUES (:pid, 'u', 'pro', :cur, :net, "
                "'addr', :idx, :path, 1, 1, 1, 'pending', 0, 3, :now, :exp, :now)"
            ),
            {
                "pid": uuid.uuid4().hex,
                "cur": currency,
                "net": network,
                "idx": index,
                "path": path,
                "now": now,
                "exp": now + timedelta(minutes=30),
            },
        )


def _billing_order(engine, *, index: int, path: str) -> None:
    order_id = uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(
            sa.text("INSERT INTO configurations (environment, config_key, config_value) VALUES ('production', :k, :v)"),
            {
                "k": f"crypto_order:{order_id}",
                "v": json.dumps({"order_id": order_id, "derivation_index": index, "derivation_path": path}),
            },
        )


def test_the_migration_seeds_every_sequence_past_everything_already_issued(pg_url, wallet_env, monkeypatch):
    engine = _schema_at_previous_head(pg_url)
    _payment(engine, currency="BTC", network="BTC", index=41, path="m/84'/0'/0'/0/41")
    _payment(engine, currency="ETH", network="ETH", index=9, path="m/44'/60'/0'/0/9")
    _payment(engine, currency="USDT", network="ERC20", index=12, path="m/44'/60'/0'/0/12")
    _payment(engine, currency="USDT", network="TRC20", index=3, path="m/44'/195'/0'/0/3")
    _payment(engine, currency="BTC", network="BTC", index=None, path=None)  # pre-c8d9e0f1a2b3 row
    _billing_order(engine, index=15, path="m/44'/60'/0'/0/15")
    # The file counter stores the NEXT index. ETH's is behind the database;
    # USDT_TRC20's is ahead of it (issued by a request whose save failed).
    wallet_env.write_text(json.dumps({"ETH": 7, "USDT_ERC20": 11, "USDT_TRC20": 20}))

    _alembic(pg_url, "upgrade", NEW_REVISION)

    from payments.crypto.address_generator import AddressGenerator

    _bind_payments_database(monkeypatch, engine)
    gen = AddressGenerator()
    assert gen.reserve_index("BTC") == 42  # past crypto_payments' 41
    assert gen.reserve_index("ETH") == 16  # past billing's 15 (> ERC20 12 > ETH 9 > file 11)
    assert gen.reserve_index("USDT_ERC20") == 17  # the same sequence as ETH
    assert gen.reserve_index("USDT_TRC20") == 20  # past the file counter's 20 (> 3)
    assert json.loads(wallet_env.read_text()) == {"ETH": 7, "USDT_ERC20": 11, "USDT_TRC20": 20}, (
        "the sequence path wrote to the file counter"
    )
    engine.dispose()


def test_concurrent_reservations_in_one_process_are_distinct(pg_url, wallet_env, monkeypatch):
    engine = _schema_at_previous_head(pg_url)
    _alembic(pg_url, "upgrade", NEW_REVISION)

    from payments.crypto.address_generator import AddressGenerator

    _bind_payments_database(monkeypatch, engine)
    n = 12
    barrier = threading.Barrier(n)
    drawn: list[int] = []
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            gen = AddressGenerator()  # separate instances: no shared in-memory state
            barrier.wait()
            currency = "ETH" if i % 2 else "USDT_ERC20"
            drawn.extend(gen.reserve_index(currency) for _ in range(10))
        except BaseException as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert sorted(drawn) == list(range(n * 10)), "ETH and USDT_ERC20 did not share one gap-free index space"
    assert not wallet_env.exists()
    engine.dispose()


@pytest.mark.slow
def test_concurrent_reservations_across_processes_are_distinct(pg_url, wallet_env):
    """Processes that share NO file (each gets its own counter path, as pods
    on separate hosts do) and find the database only through ``DATABASE_URL``,
    as a deployed worker does, still never draw the same index."""
    engine = _schema_at_previous_head(pg_url)
    _alembic(pg_url, "upgrade", NEW_REVISION)

    script = textwrap.dedent(
        """
        import json, sys
        from payments.crypto.address_generator import AddressGenerator
        gen = AddressGenerator()
        print(json.dumps([gen.reserve_index(sys.argv[1]) for _ in range(int(sys.argv[2]))]))
        """
    )
    procs = []
    for i, currency in enumerate(["ETH", "USDT_ERC20", "ETH", "USDT_ERC20"]):
        env = {
            **os.environ,
            "DATABASE_URL": pg_url,
            "APP_ENV": "test",
            "HOPEFX_CRYPTO_COUNTER_PATH": str(wallet_env.parent / f"host-{i}" / "counter.json"),
            "PYTHONPATH": str(REPO),
        }
        procs.append(
            subprocess.Popen(
                [sys.executable, "-c", script, currency, "25"],
                cwd=str(REPO),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    drawn: list[int] = []
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err
        drawn.extend(json.loads(out.strip().splitlines()[-1]))

    assert sorted(drawn) == list(range(100)), f"{len(drawn) - len(set(drawn))} indices drawn twice across processes"
    for i in range(4):
        assert not (wallet_env.parent / f"host-{i}" / "counter.json").exists()
    engine.dispose()


def test_a_missing_sequence_refuses_and_names_the_migration(pg_url, wallet_env, monkeypatch):
    """A PostgreSQL database that never ran this revision (for example one built
    by the ``create_all()`` startup fallback) has no sequence. It must refuse,
    and say what to run -- not count from the file."""
    engine = _schema_at_previous_head(pg_url)

    from payments.crypto.address_generator import AddressGenerator

    _bind_payments_database(monkeypatch, engine)
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        AddressGenerator().reserve_index("BTC")
    assert not wallet_env.exists()
    engine.dispose()


def test_downgrade_drops_the_sequences(pg_url, wallet_env, monkeypatch):
    engine = _schema_at_previous_head(pg_url)
    _alembic(pg_url, "upgrade", NEW_REVISION)
    _alembic(pg_url, "downgrade", PREVIOUS_REVISION)
    with engine.connect() as conn:
        names = set(sa.inspect(conn).get_sequence_names())
    assert not {"crypto_hd_index_btc", "crypto_hd_index_eth", "crypto_hd_index_trc20"} & names
    engine.dispose()
