# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A trade's side is BUY or SELL at the persistence boundary — nothing else.

On a migrated database ``trades.side`` is the ``orderside`` ENUM('BUY', 'SELL')
(``1b0666c43575``), and the model declared it ``String(20)`` with a
``server_default="unknown"`` no migration ever created. Measured 2026-09-25 on
SQLite and on a real PostgreSQL 16 server, every production write path failed:

* ``brokers/__init__.py::_persist_trade_record`` and
  ``brokers/paper_trading.py::_persist_trade`` passed a raw
  ``database.models.OrderSide`` member into a string column — PostgreSQL
  answers ``can't adapt type 'OrderSide'``, sqlite3 ``type 'OrderSide' is not
  supported``. Both handlers logged at WARNING and carried on, so **no paper
  trade was ever persisted**, and nothing said so at a level production shows.
* ``scripts/seed_demo_trades.py`` wrote lowercase ``'buy'`` / ``'sell'`` —
  ``invalid input value for enum orderside``.
* Omitting side relied on the model's ``'unknown'`` default, which the column
  does not have — a NOT NULL violation (and, had it existed, the ENUM would
  refuse it anyway).

The owner's decision (MASTER_OUTSTANDING §A9): one side vocabulary, BUY/SELL,
enforced at the persistence boundary; the database ENUM stays. ``core/side.py``
is the one normaliser; the ``Trade.side`` column type applies it on every bind.

Backends: a database built by ``alembic upgrade head`` — never ``create_all()``
— on SQLite always, and on PostgreSQL when one is configured (same variables as
``test_migration_chain_runs_on_postgres.py``; ``HOPEFX_REQUIRE_POSTGRES=1``
turns the skip into a failure).
"""

from __future__ import annotations

import enum
import logging
import os
import uuid
import warnings
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import sessionmaker

pytestmark = [pytest.mark.unit]

_URL_VARS = ("TEST_POSTGRES_URL", "HOPEFX_TEST_POSTGRES_URL", "HOPEFX_TEST_PG_URL", "DATABASE_URL")


# ── the normaliser ────────────────────────────────────────────────────────────


class _LowerSide(enum.Enum):
    """Shape of ``database.models.OrderSide`` / ``brokers.OrderSide``."""

    BUY = "buy"
    SELL = "sell"


class _UpperSide(enum.Enum):
    """Shape of ``brokers.base.OrderSide``."""

    BUY = "BUY"
    SELL = "SELL"


class _IntSide(enum.Enum):
    """An enum whose values are not spellings — its NAME is the side."""

    BUY = 1
    SELL = -1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("BUY", "BUY"),
        ("buy", "BUY"),
        ("Buy", "BUY"),
        ("  buy ", "BUY"),
        ("LONG", "BUY"),
        ("long", "BUY"),
        ("SELL", "SELL"),
        ("sell", "SELL"),
        ("SHORT", "SELL"),
        ("short", "SELL"),
        # str() of an enum member — brokers/paper_trading.py compares against
        # "ORDERSIDE.BUY" in five places, so the spelling does reach it.
        ("OrderSide.BUY", "BUY"),
        ("OrderSide.SELL", "SELL"),
        (_LowerSide.BUY, "BUY"),
        (_LowerSide.SELL, "SELL"),
        (_UpperSide.BUY, "BUY"),
        (_UpperSide.SELL, "SELL"),
        (_IntSide.BUY, "BUY"),
        (_IntSide.SELL, "SELL"),
    ],
)
def test_every_accepted_spelling_normalises_to_buy_or_sell(raw, expected):
    from core.side import normalise_side

    result = normalise_side(raw)
    assert result == expected
    # A plain str, not a str subclass — psycopg2 adapts by exact type.
    assert type(result) is str


def test_the_real_side_enums_in_this_repository_normalise():
    from brokers import OrderSide as BrokersOrderSide
    from brokers.base import OrderSide as BaseOrderSide
    from core.side import normalise_side
    from core.types import Side
    from database.models import OrderSide as DBOrderSide

    for buy, sell in (
        (DBOrderSide.BUY, DBOrderSide.SELL),
        (BaseOrderSide.BUY, BaseOrderSide.SELL),
        (BrokersOrderSide.BUY, BrokersOrderSide.SELL),
        (Side.BUY, Side.SELL),
    ):
        assert normalise_side(buy) == "BUY"
        assert normalise_side(sell) == "SELL"


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "unknown", "both", "flat", "b", "s", "bid", "ask", "buyer", "longshort", None, 0, 1, -1, True, 1.0],
)
def test_an_unknown_spelling_raises_and_never_defaults(raw):
    from core.side import UnknownSideError, normalise_side

    with pytest.raises(UnknownSideError):
        normalise_side(raw)


def test_unknown_side_error_is_a_value_error():
    """Callers that already catch ValueError keep catching it."""
    from core.side import UnknownSideError

    assert issubclass(UnknownSideError, ValueError)


def test_an_enum_with_an_unrecognised_member_raises():
    from core.side import UnknownSideError, normalise_side

    class Weird(enum.Enum):
        HOLD = "hold"

    with pytest.raises(UnknownSideError):
        normalise_side(Weird.HOLD)


# ── migrated databases ───────────────────────────────────────────────────────


def _pg_admin_url():
    for var in _URL_VARS:
        raw = os.getenv(var, "")
        if not raw:
            continue
        scheme = raw.split("://", 1)[0].split("+", 1)[0]
        if scheme not in ("postgresql", "postgres"):
            continue
        return sa.engine.make_url(raw.replace("postgres://", "postgresql://", 1)).set(drivername="postgresql")
    return None


def _pg_unavailable(reason: str) -> None:
    message = (
        "UNPROVEN ON POSTGRESQL — trades.side persistence was NOT checked against the "
        "real `orderside` ENUM. Set TEST_POSTGRES_URL=postgresql://user@host:port/db "
        "(HOPEFX_REQUIRE_POSTGRES=1 makes this a failure). Reason: " + reason
    )
    if os.getenv("HOPEFX_REQUIRE_POSTGRES", "").strip().lower() in ("1", "true", "yes"):
        pytest.fail(message, pytrace=False)
    warnings.warn(message, stacklevel=2)
    pytest.skip(message)


def _migrate(url: str) -> None:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    # alembic/env.py lets DATABASE_URL override the ini — pin it to this database.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL", url)
        command.upgrade(cfg, "head")


@pytest.fixture(scope="module")
def _sqlite_migrated(tmp_path_factory) -> Iterator[sa.Engine]:
    url = f"sqlite:///{tmp_path_factory.mktemp('side') / 'migrated.db'}"
    _migrate(url)
    engine = sa.create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def _pg_migrated() -> Iterator[sa.Engine]:
    admin_url = _pg_admin_url()
    if admin_url is None:
        _pg_unavailable(f"none of {', '.join(_URL_VARS)} names a postgresql:// server")
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
    try:
        with admin.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except sa.exc.OperationalError as exc:
        admin.dispose()
        _pg_unavailable(f"the configured server is not reachable: {exc.orig}")
    name = f"hopefx_side_{uuid.uuid4().hex[:10]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = admin_url.set(database=name).render_as_string(hide_password=False)
    engine = None
    try:
        _migrate(url)
        engine = sa.create_engine(url)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(params=["sqlite", "postgresql"])
def migrated(request) -> Iterator[sa.Engine]:
    """A migrated database with an empty ``trades`` table."""
    engine = request.getfixturevalue("_sqlite_migrated" if request.param == "sqlite" else "_pg_migrated")
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM trades"))
    yield engine


def _stored_sides(engine: sa.Engine) -> list[str]:
    with engine.connect() as conn:
        return [row[0] for row in conn.execute(sa.text("SELECT side FROM trades ORDER BY id"))]


def _base_position(side):
    from brokers.base import Position

    return Position(
        symbol="XAUUSD",
        side=side,
        quantity=1.0,
        entry_price=2000.0,
        current_price=2010.0,
        unrealized_pnl=10.0,
    )


# ── (a) paper trading persists BUY and SELL ──────────────────────────────────


def test_paper_trading_broker_persists_a_buy_and_a_sell(migrated, caplog):
    from brokers.paper_trading import PaperTradingBroker

    broker = PaperTradingBroker(session_factory=sessionmaker(bind=migrated), slippage_model="zero", seed=0)
    with caplog.at_level(logging.WARNING):
        broker._persist_trade(_base_position("BUY"), 2010.0, 10.0)
        broker._persist_trade(_base_position("SELL"), 1990.0, 10.0)

    assert _stored_sides(migrated) == ["BUY", "SELL"], caplog.text


def test_paper_trading_broker_persists_legacy_long_short_positions(migrated):
    from brokers.paper_trading import PaperTradingBroker

    broker = PaperTradingBroker(session_factory=sessionmaker(bind=migrated), slippage_model="zero", seed=0)
    # Position normalises LONG/SHORT itself; a position whose side was set
    # after construction (object.__setattr__ bypasses __post_init__) reaches
    # the persister as the raw string.
    long_pos, short_pos = _base_position("LONG"), _base_position("SHORT")
    object.__setattr__(short_pos, "side", "short")
    broker._persist_trade(long_pos, 2010.0, 10.0)
    broker._persist_trade(short_pos, 1990.0, 10.0)

    assert _stored_sides(migrated) == ["BUY", "SELL"]


# ── (c) the brokers/__init__ persist path ────────────────────────────────────


def _legacy_paper_broker_class():
    """``brokers/__init__.py``'s own PaperTradingBroker, compiled from its source.

    The package rebinds the name to ``brokers.paper_trading.PaperTradingBroker``
    at the end of the module (MASTER_OUTSTANDING §A6). Nothing else holds the
    original class, so the cyclic GC collects it and ``_persist_trade_record``
    cannot run in any process today — see the test below. The class body is
    compiled here from the real source, in the real module's globals, so the
    function that would run if it were ever revived is the one under test.
    """
    import ast
    from pathlib import Path

    import brokers

    tree = ast.parse(Path(brokers.__file__).read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PaperTradingBroker")
    namespace = dict(vars(brokers))
    exec(compile(ast.Module(body=[node], type_ignores=[]), brokers.__file__, "exec"), namespace)  # nosec B102 — compiles this repository's own source
    cls = namespace["PaperTradingBroker"]
    assert cls is not brokers.PaperTradingBroker and hasattr(cls, "_persist_trade_record")
    return cls


def test_the_brokers_package_persist_path_is_unreachable_today():
    """Pins the finding: no live object can call ``_persist_trade_record``.

    If this fails, the legacy broker is reachable again — the persistence
    tests below then cover a live path rather than a dormant one.
    """
    import gc

    import brokers

    gc.collect()
    assert brokers.PaperTradingBroker.__module__ == "brokers.paper_trading"
    assert not hasattr(brokers.PaperTradingBroker, "_persist_trade_record")
    assert not [
        c
        for c in brokers.BaseBroker.__subclasses__()
        if c.__name__ == "PaperTradingBroker" and c.__module__ == "brokers"
    ]


def test_brokers_package_paper_broker_persists_a_buy_and_a_sell(migrated, caplog):
    broker = _legacy_paper_broker_class()(session_factory=sessionmaker(bind=migrated), user_id="u-1", seed=0)
    record = {
        "symbol": "XAUUSD",
        "quantity": 1.0,
        "entry_price": 2000.0,
        "exit_price": 2010.0,
        "realized_pnl": 10.0,
        "commission": 0.0,
        "opened_at": 1_750_000_000.0,
        "closed_at": 1_750_000_600.0,
    }
    with caplog.at_level(logging.WARNING):
        # The record carries `pos.side.value` — brokers.OrderSide is lowercase.
        broker._persist_trade_record({**record, "side": "buy"})
        broker._persist_trade_record({**record, "side": "sell"})

    assert _stored_sides(migrated) == ["BUY", "SELL"], caplog.text


def test_brokers_package_refuses_a_record_with_no_recognisable_side(migrated, caplog):
    """It used to default a missing side to BUY — a guessed direction on a
    money record. Now nothing is written, and the refusal is an ERROR."""
    broker = _legacy_paper_broker_class()(session_factory=sessionmaker(bind=migrated), user_id="u-1", seed=0)
    with caplog.at_level(logging.ERROR):
        broker._persist_trade_record({"symbol": "XAUUSD", "quantity": 1.0, "entry_price": 1.0})
        broker._persist_trade_record({"symbol": "XAUUSD", "quantity": 1.0, "entry_price": 1.0, "side": "hold"})

    assert _stored_sides(migrated) == []
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 2, caplog.text


def test_paper_trading_refuses_an_unrecognisable_side_instead_of_selling(migrated, caplog):
    """`_persist_trade` recorded anything that was not a buy as a SELL."""
    from brokers.paper_trading import PaperTradingBroker

    broker = PaperTradingBroker(session_factory=sessionmaker(bind=migrated), slippage_model="zero", seed=0)
    pos = _base_position("BUY")
    object.__setattr__(pos, "side", "flat")
    with caplog.at_level(logging.ERROR):
        broker._persist_trade(pos, 2010.0, 10.0)

    assert _stored_sides(migrated) == []
    assert any(r.levelno >= logging.ERROR for r in caplog.records), caplog.text


# ── the ORM boundary itself (what seed_demo_trades.py and any writer reach) ──


@pytest.mark.parametrize("spelling", ["buy", "BUY", "long", "LONG"])
def test_the_trade_model_normalises_every_writer(migrated, spelling):
    from database.models import OrderSide, Trade, TradeStatus

    session = sessionmaker(bind=migrated)()
    try:
        session.add(
            Trade(trade_id=str(uuid.uuid4()), symbol="XAUUSD", side=spelling, entry_price=1.0, entry_quantity=1.0)
        )
        session.add(
            Trade(trade_id=str(uuid.uuid4()), symbol="XAUUSD", side=OrderSide.SELL, entry_price=1.0, entry_quantity=1.0)
        )
        session.add(
            Trade(
                trade_id=str(uuid.uuid4()),
                symbol="XAUUSD",
                side="short",
                entry_price=1.0,
                entry_quantity=1.0,
                status=TradeStatus.CLOSED,
            )
        )
        session.commit()
    finally:
        session.close()

    assert _stored_sides(migrated) == ["BUY", "SELL", "SELL"]


def test_the_trade_model_refuses_an_unknown_side(migrated):
    from core.side import UnknownSideError
    from database.models import Trade

    session = sessionmaker(bind=migrated)()
    try:
        session.add(
            Trade(trade_id=str(uuid.uuid4()), symbol="XAUUSD", side="unknown", entry_price=1.0, entry_quantity=1.0)
        )
        with pytest.raises(sa.exc.StatementError) as excinfo:
            session.commit()
        assert isinstance(excinfo.value.orig, UnknownSideError)
    finally:
        session.rollback()
        session.close()
    assert _stored_sides(migrated) == []


def test_omitting_side_is_refused_rather_than_defaulted(migrated):
    """The model's `server_default="unknown"` was a value the ENUM cannot hold
    on a column that had no default at all. Omitting side is an error."""
    from database.models import Trade

    assert Trade.__table__.c.side.server_default is None
    session = sessionmaker(bind=migrated)()
    try:
        session.add(Trade(trade_id=str(uuid.uuid4()), symbol="XAUUSD", entry_price=1.0, entry_quantity=1.0))
        with pytest.raises(sa.exc.IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_the_seed_script_rows_persist(migrated):
    """scripts/seed_demo_trades.py writes lowercase 'buy'/'sell'."""
    from datetime import datetime

    from scripts.seed_demo_trades import generate_trades

    rows = generate_trades(6, datetime(2026, 1, 1))
    assert {r["side"] for r in rows} <= {"buy", "sell"}

    from database.models import Trade, TradeStatus

    session = sessionmaker(bind=migrated)()
    try:
        for r in rows:
            session.add(
                Trade(
                    trade_id=r["trade_id"],
                    symbol=r["symbol"],
                    side=r["side"],
                    entry_price=r["entry_price"],
                    entry_quantity=r["entry_quantity"],
                    status=TradeStatus.CLOSED,
                )
            )
        session.commit()
    finally:
        session.close()

    assert _stored_sides(migrated) == [r["side"].upper() for r in rows]


# ── (5) the read path ────────────────────────────────────────────────────────


def test_a_persisted_trade_reads_back_through_the_history_serialisers(migrated):
    from api.trading import _trade_to_dict
    from brokers.paper_trading import PaperTradingBroker
    from core.side import is_long
    from database.models import Trade

    broker = PaperTradingBroker(session_factory=sessionmaker(bind=migrated), slippage_model="zero", seed=0)
    broker._persist_trade(_base_position("BUY"), 2010.0, 10.0)
    broker._persist_trade(_base_position("SELL"), 1990.0, 10.0)

    session = sessionmaker(bind=migrated)()
    try:
        buy, sell = session.query(Trade).order_by(Trade.id).all()
        assert (buy.side, sell.side) == ("BUY", "SELL")
        assert (_trade_to_dict(buy)["side"], _trade_to_dict(sell)["side"]) == ("BUY", "SELL")
        # Trade.to_dict read `self.side.value` — an AttributeError on every row.
        assert (buy.to_dict()["side"], sell.to_dict()["side"]) == ("BUY", "SELL")
        assert "BUY" in repr(buy)
        assert is_long(buy.side) and not is_long(sell.side)
        # A query filtering on any accepted spelling finds the row.
        assert session.query(Trade).filter(Trade.side == "long").count() == 1
    finally:
        session.close()


# ── the other two encodings of "long" (MASTER_OUTSTANDING §A9) ───────────────


def test_the_reconciler_and_broker_position_use_the_one_vocabulary():
    from brokers import base
    import core.position_reconciler as reconciler
    from core import side

    assert reconciler._LONG_SIDES is side.LONG_SPELLINGS
    assert reconciler._SHORT_SIDES is side.SHORT_SPELLINGS
    assert base._SIDE_BUY_ALIASES is side.LONG_SPELLINGS
    assert base._SIDE_SELL_ALIASES is side.SHORT_SPELLINGS


def test_position_net_exposure_counts_an_uppercase_long_as_long():
    """position_repository's SQL case matched only lowercase 'long'/'buy', so a
    position stored as 'BUY' or 'LONG' was netted as a SHORT."""
    from sqlalchemy.dialects import sqlite

    from database.repositories.position_repository import _long_side_condition

    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        for spelling in ("BUY", "LONG", "buy", "long", "Long"):
            stmt = sa.select(_long_side_condition(sa.literal(spelling)))
            assert conn.execute(stmt).scalar() in (1, True), spelling
        for spelling in ("SELL", "short", "unknown"):
            stmt = sa.select(_long_side_condition(sa.literal(spelling)))
            assert conn.execute(stmt).scalar() in (0, False), spelling
    assert "lower" in str(_long_side_condition(sa.literal("x")).compile(dialect=sqlite.dialect())).lower()
