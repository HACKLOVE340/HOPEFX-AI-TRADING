# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`execution/fix_adapter.py` — the FIX 4.4 order path, measured rather than read.

The adapter measured 35%. What was uncovered was not incidental: the whole
`_QuickfixApp` callback surface, both pyfixmsg wire builders, the reader loop,
the dispatcher and the router hook — that is, every line that runs when an
order is actually on the wire. The covered third was dataclasses and the
circuit breaker.

Nothing in this environment can import `quickfix`: it is a C extension needing
`libquickfix-dev`, so `requirements-ci.txt` excludes it and the module falls
back to `_FIX_BACKEND = "simplefix"`. Production installs it
(`requirements.txt:185`, `quickfix==1.15.1`). So the backend that carries real
orders is the one no test could reach, and "no test could reach it" is how a
module gets to 35% while looking tested.

These tests reach it with `_FakeFix` — a hand-written FIX 4.4 stand-in, not a
`MagicMock`. A `MagicMock` accepts `getField` with any argument and returns a
truthy mock for every field, so every one of the tests below would pass against
an adapter that read the wrong tag. `_FakeFix` models the two behaviours that
matter and nothing else: a field carries a tag, and asking a message for a tag
it does not carry raises `FieldNotFound`.

That second behaviour is where the fake had to be built from evidence rather
than from memory, and it is what `TestAnAbsentFieldIsTheOneThingTheseHandlersExistFor`
is about. See that class for the citation.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import sys
import threading
import time
import types
from typing import Any

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import execution.fix_adapter as fa
from execution.fix_adapter import (
    CircuitBreaker,
    FIXAdapter,
    FIXExecType,
    FIXFillReport,
    FIXOrdType,
    FIXOrder,
    FIXSide,
    _get_fix_field,
    _QuickfixApp,
)

SOH = "\x01"

#: The FIX password used throughout. Named once so the literal is
#: allowlisted in one place rather than at six call sites.
TEST_PASSWORD = "pass"  # pragma: allowlist secret


# ---------------------------------------------------------------------------
# A FIX 4.4 stand-in, built to the real library's contract
# ---------------------------------------------------------------------------


class _FIXException(Exception):
    """Mirrors `quickfix.FIXException`, which derives from `Exception`."""


class _FieldNotFound(_FIXException):
    """Mirrors `quickfix.FieldNotFound(FIXException)`.

    Deliberately *not* an `AttributeError`, `TypeError`, `ValueError` or
    `KeyError`. That is the whole point — see
    `TestAnAbsentFieldIsTheOneThingTheseHandlersExistFor`.
    """


class _Field:
    """A FIX field: a tag and a value. Subclasses fix the tag."""

    tag = 0

    def __init__(self, value: Any = None) -> None:
        self._value = value

    def getTag(self) -> int:
        return self.tag

    def getValue(self) -> Any:
        return self._value

    def setValue(self, value: Any) -> None:
        self._value = value

    def getString(self) -> str:
        return "" if self._value is None else str(self._value)


def _field(name: str, tag: int) -> type[_Field]:
    return type(name, (_Field,), {"tag": tag})


class _FakeMessage:
    """`getField` mutates the field in place *and* returns it, as quickfix does."""

    def __init__(self, fields: dict[int, Any] | None = None, header: dict[int, Any] | None = None) -> None:
        self.fields: dict[int, Any] = dict(fields or {})
        self._header = _FakeMessage(header) if header is not None else None

    def getHeader(self) -> _FakeMessage:
        if self._header is None:
            raise AttributeError("message has no header")
        return self._header

    def getField(self, field_obj: _Field) -> _Field:
        if field_obj.tag not in self.fields:
            raise _FieldNotFound(field_obj.tag)
        field_obj.setValue(self.fields[field_obj.tag])
        return field_obj

    def setField(self, field_obj: _Field) -> None:
        self.fields[field_obj.tag] = field_obj.getValue()


class _FakeSessionSettings:
    """Reads the config at construction, as the real one does.

    `_start_quickfix` deletes its generated temp file immediately afterwards,
    so capturing the text here is the only way to assert on what was written.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.text = pathlib.Path(path).read_text(encoding="utf-8")


class _FakeInitiator:
    def __init__(self, app: Any, store: Any, settings: Any, log: Any) -> None:
        self.app = app
        self.store = store
        self.settings = settings
        self.log = log
        self.started = False
        self.stopped = False
        self.sessions = ["SESSION-1", "SESSION-2"]

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def getSessions(self) -> list[str]:
        return self.sessions


def _make_fake_fix() -> tuple[types.SimpleNamespace, types.SimpleNamespace, list[tuple[Any, Any]]]:
    """Build the `fix` / `fix44` stand-ins and the list that records sends."""
    sent: list[tuple[Any, Any]] = []

    class _Session:
        @staticmethod
        def sendToTarget(message: Any, session_id: Any) -> None:
            sent.append((message, session_id))

    fix = types.SimpleNamespace(
        FIXException=_FIXException,
        FieldNotFound=_FieldNotFound,
        # Header / admin
        MsgType=_field("MsgType", 35),
        BeginString=_field("BeginString", 8),
        Username=_field("Username", 553),
        Password=_field("Password", 554),
        Text=_field("Text", 58),
        RefSeqNum=_field("RefSeqNum", 45),
        SessionRejectReason=_field("SessionRejectReason", 373),
        CxlRejReason=_field("CxlRejReason", 102),
        # Order / execution
        ClOrdID=_field("ClOrdID", 11),
        OrderID=_field("OrderID", 37),
        ExecType=_field("ExecType", 150),
        Symbol=_field("Symbol", 55),
        Side=_field("Side", 54),
        LastQty=_field("LastQty", 32),
        AvgPx=_field("AvgPx", 6),
        LeavesQty=_field("LeavesQty", 151),
        CumQty=_field("CumQty", 14),
        TransactTime=_field("TransactTime", 60),
        OrdType=_field("OrdType", 40),
        OrderQty=_field("OrderQty", 38),
        TimeInForce=_field("TimeInForce", 59),
        Price=_field("Price", 44),
        StopPx=_field("StopPx", 99),
        Account=_field("Account", 1),
        # Constants
        MsgType_Logon="A",
        MsgType_Logout="5",
        MsgType_Reject="3",
        MsgType_ExecutionReport="8",
        BeginString_FIX44="FIX.4.4",
        # Session plumbing
        Session=_Session,
        SessionSettings=_FakeSessionSettings,
        FileStoreFactory=lambda settings: ("store", settings),
        FileLogFactory=lambda settings: ("log", settings),
        SocketInitiator=_FakeInitiator,
    )

    fix44 = types.SimpleNamespace(
        NewOrderSingle=lambda: _FakeMessage(header={}),
    )
    return fix, fix44, sent


@pytest.fixture
def fake_fix(monkeypatch: pytest.MonkeyPatch):
    """Install the FIX 4.4 stand-in over the module's backend globals."""
    fix, fix44, sent = _make_fake_fix()
    monkeypatch.setattr(fa, "fix", fix)
    monkeypatch.setattr(fa, "fix44", fix44)
    return types.SimpleNamespace(fix=fix, fix44=fix44, sent=sent)


@pytest.fixture
def captured() -> list[FIXFillReport]:
    return []


@pytest.fixture
def app(fake_fix, captured: list[FIXFillReport]) -> _QuickfixApp:
    return _QuickfixApp(
        on_exec_report=captured.append,
        circuit_breaker=CircuitBreaker(threshold_ms=100.0),
        username="user",
        password=TEST_PASSWORD,
    )


def _exec_report_message(**overrides: Any) -> _FakeMessage:
    """A complete FIX 4.4 ExecutionReport, minus anything named in `overrides`."""
    fields: dict[int, Any] = {
        11: "CL-1",  # ClOrdID
        37: "BROKER-1",  # OrderID
        150: "2",  # ExecType = FILL
        55: "XAUUSD",  # Symbol
        54: "1",  # Side = BUY
        32: 1.0,  # LastQty
        6: 1950.25,  # AvgPx
        151: 0.0,  # LeavesQty
        14: 1.0,  # CumQty
    }
    fields.update(overrides.pop("fields", {}))
    for tag in overrides.pop("drop", []):
        fields.pop(tag, None)
    return _FakeMessage(fields, header={35: "8"})


# ---------------------------------------------------------------------------
# The exception type every handler in this module was built around
# ---------------------------------------------------------------------------


class TestAnAbsentFieldIsTheOneThingTheseHandlersExistFor:
    """`quickfix` raises a type none of this module's handlers used to name.

    Evidence, from the quickfix 1.15.1 sdist that `requirements.txt:185` pins:

      * `C++/FieldMap.h:156` — `FieldBase& getField( FieldBase& field ) const
        throw( FieldNotFound )`, and `getFieldRef` (line 171) `throw
        FieldNotFound( tag )` when the tag is absent.
      * `quickfix.py:194` — `class FieldNotFound(FIXException)`.
      * `quickfix.py:143` — `class FIXException(Exception)`.

    So an absent field raises something that is not `AttributeError`, not
    `TypeError`, not `ValueError` and not `KeyError` — the four types the
    handlers below named. Against the simulation backend that costs nothing,
    because nothing raises. Against the backend that carries money, every
    "this field is optional" and "reject the order" path was unreachable.

    Two of them are on the money path: `_handle_exec_report` and
    `_handle_order_cancel_reject` both promise to resolve the caller's pending
    future on a malformed report. If the handler dies before reaching
    `_reject_pending`, the future is never resolved and `send_order` waits out
    its full 30-second timeout instead of failing immediately.
    """

    def test_the_fake_reproduces_the_real_exception_hierarchy(self) -> None:
        """If this ever stops holding, the fake has stopped modelling quickfix."""
        assert issubclass(_FieldNotFound, _FIXException)
        assert issubclass(_FIXException, Exception)
        assert not issubclass(_FieldNotFound, (AttributeError, TypeError, ValueError, KeyError))

    def test_the_real_library_agrees_where_it_is_installed(self) -> None:
        """Checked against the C extension itself wherever it can be imported —
        the production image installs it, this one cannot build it."""
        quickfix = pytest.importorskip("quickfix", reason="C extension, absent unless libquickfix-dev is present")
        assert issubclass(quickfix.FieldNotFound, Exception)
        assert not issubclass(quickfix.FieldNotFound, (AttributeError, TypeError, ValueError, KeyError))

    def test_an_absent_optional_field_reads_as_empty(self, fake_fix) -> None:
        """`_get_fix_field`'s stated contract: "" means not present."""
        message = _FakeMessage({58: "hello"})
        assert _get_fix_field(message, fake_fix.fix.Text(), "ctx") == "hello"
        assert _get_fix_field(message, fake_fix.fix.CxlRejReason(), "ctx") == ""

    def test_a_logout_with_no_text_is_logged_not_raised(self, app, fake_fix) -> None:
        """IBKR sends a bare Logout on an ordinary disconnect. Tag 58 is
        optional; before this was fixed, the absence of it took down the
        callback instead of logging the disconnect."""
        app.fromAdmin(_FakeMessage({}, header={35: "5"}), "SESSION-1")

    def test_a_session_reject_with_no_reason_or_text_is_logged_not_raised(self, app) -> None:
        app.fromAdmin(_FakeMessage({45: "7"}, header={35: "3"}), "SESSION-1")

    def test_an_exec_report_missing_a_required_field_rejects_the_pending_order(
        self, app, captured: list[FIXFillReport]
    ) -> None:
        """The money-path consequence, asserted as an outcome.

        A report with no AvgPx must resolve the caller's future as REJECTED.
        Before the fix the handler died on the way to `_reject_pending` and the
        caller hung for 30 seconds.
        """
        app._handle_exec_report(_exec_report_message(drop=[6]))

        assert len(captured) == 1, "no rejection was dispatched — the caller is left waiting"
        assert captured[0].exec_type is FIXExecType.REJECTED
        assert captured[0].cl_ord_id == "CL-1"

    def test_a_cancel_reject_with_no_text_still_rejects_the_pending_order(
        self, app, captured: list[FIXFillReport]
    ) -> None:
        """Tag 58 is optional on OrderCancelReject. Its absence must not stop
        the caller being told the cancel was refused."""
        app._handle_order_cancel_reject(_FakeMessage({11: "CL-9", 102: "1"}))

        assert len(captured) == 1
        assert captured[0].exec_type is FIXExecType.REJECTED
        assert captured[0].cl_ord_id == "CL-9"
        assert "reason=1" in captured[0].text

    def test_an_application_message_without_a_clordid_does_not_raise_in_toapp(self, app) -> None:
        """`toApp` runs on the *send* path. An exception here reaches quickfix's
        C++ callback rather than the caller."""
        app.toApp(_FakeMessage({55: "XAUUSD"}), "SESSION-1")
        assert app._send_times == {}

    def test_the_helper_reports_the_backends_own_absent_type(self, fake_fix) -> None:
        assert _FieldNotFound in fa._fix_absent_errors()

    def test_the_helper_is_empty_when_no_backend_is_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Simulation and simplefix modes have no library and therefore no
        library exception. The handlers must still compile their except clause."""
        monkeypatch.setattr(fa, "fix", None)
        assert fa._fix_absent_errors() == ()

    def test_a_backend_whose_attribute_is_not_an_exception_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`except` raises TypeError if handed a non-exception. A backend that
        exposes `FieldNotFound` as anything else must not reach the tuple."""
        monkeypatch.setattr(fa, "fix", types.SimpleNamespace(FieldNotFound="not a class"))
        assert fa._fix_absent_errors() == ()
        monkeypatch.setattr(fa, "fix", types.SimpleNamespace(FieldNotFound=dict))
        assert fa._fix_absent_errors() == ()


# ---------------------------------------------------------------------------
# _get_fix_field
# ---------------------------------------------------------------------------


class TestReadingAFieldOffAMessage:
    def test_it_returns_the_string_value(self, fake_fix) -> None:
        assert _get_fix_field(_FakeMessage({58: "rejected"}), fake_fix.fix.Text()) == "rejected"

    def test_it_stringifies_a_numeric_value(self, fake_fix) -> None:
        assert _get_fix_field(_FakeMessage({45: 42}), fake_fix.fix.RefSeqNum()) == "42"

    def test_an_absent_field_is_empty_with_no_context_label(self, fake_fix) -> None:
        assert _get_fix_field(_FakeMessage({}), fake_fix.fix.Text()) == ""

    def test_the_context_label_reaches_the_debug_log(self, fake_fix, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="execution.fix_adapter"):
            _get_fix_field(_FakeMessage({}), fake_fix.fix.Text(), "fix.fromAdmin: Logout Text")
        assert "fix.fromAdmin: Logout Text" in caplog.text

    def test_an_unreadable_value_is_empty_rather_than_an_exception(self, fake_fix) -> None:
        class _Exploding(fake_fix.fix.Text):  # type: ignore[misc,valid-type]
            def getString(self) -> str:
                raise ValueError("corrupt field")

        assert _get_fix_field(_FakeMessage({58: "x"}), _Exploding()) == ""


# ---------------------------------------------------------------------------
# Session callbacks
# ---------------------------------------------------------------------------


class TestSessionLifecycleCallbacks:
    @pytest.mark.parametrize("callback", ["onCreate", "onLogon", "onLogout"])
    def test_each_one_logs_the_session_and_returns(self, app, callback: str, caplog) -> None:
        with caplog.at_level(logging.INFO, logger="execution.fix_adapter"):
            getattr(app, callback)("SESSION-7")
        assert "SESSION-7" in caplog.text


class TestCredentialsAreInjectedOnLogonAndNowhereElse:
    """Username/Password belong on the Logon only. Putting them on a Heartbeat
    writes credentials into the FIX message log on every interval."""

    def test_a_logon_carries_both_credentials(self, app) -> None:
        message = _FakeMessage({}, header={35: "A"})
        app.toAdmin(message, "SESSION-1")
        assert message.fields[553] == "user"
        assert message.fields[554] == TEST_PASSWORD

    @pytest.mark.parametrize("msg_type", ["0", "1", "2", "4", "5"])
    def test_no_other_admin_message_carries_them(self, app, msg_type: str) -> None:
        message = _FakeMessage({}, header={35: msg_type})
        app.toAdmin(message, "SESSION-1")
        assert 553 not in message.fields
        assert 554 not in message.fields

    def test_an_empty_username_is_not_injected(self, fake_fix) -> None:
        app = _QuickfixApp(
            on_exec_report=lambda r: None, circuit_breaker=CircuitBreaker(), username="", password=TEST_PASSWORD
        )
        message = _FakeMessage({}, header={35: "A"})
        app.toAdmin(message, "SESSION-1")
        assert 553 not in message.fields
        assert message.fields[554] == TEST_PASSWORD

    def test_an_empty_password_is_not_injected(self, fake_fix) -> None:
        app = _QuickfixApp(on_exec_report=lambda r: None, circuit_breaker=CircuitBreaker(), username="u", password="")
        message = _FakeMessage({}, header={35: "A"})
        app.toAdmin(message, "SESSION-1")
        assert message.fields[553] == "u"
        assert 554 not in message.fields

    def test_a_headerless_message_is_warned_about_not_raised(self, app, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="execution.fix_adapter"):
            app.toAdmin(_FakeMessage({}), "SESSION-1")
        assert "could not inject credentials" in caplog.text

    def test_no_backend_means_no_injection_attempt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fa, "fix", None)
        app = _QuickfixApp(
            on_exec_report=lambda r: None, circuit_breaker=CircuitBreaker(), username="u", password=TEST_PASSWORD
        )
        message = _FakeMessage({}, header={35: "A"})
        app.toAdmin(message, "SESSION-1")
        assert message.fields == {}


class TestInboundAdminMessages:
    def test_a_logout_reason_reaches_the_log(self, app, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="execution.fix_adapter"):
            app.fromAdmin(_FakeMessage({58: "MsgSeqNum too low"}, header={35: "5"}), "SESSION-1")
        assert "MsgSeqNum too low" in caplog.text

    def test_a_session_reject_reports_ref_seq_reason_and_text(self, app, caplog) -> None:
        with caplog.at_level(logging.ERROR, logger="execution.fix_adapter"):
            app.fromAdmin(
                _FakeMessage({45: "12", 373: "5", 58: "Value is incorrect"}, header={35: "3"}),
                "SESSION-1",
            )
        assert "ref_seq=12" in caplog.text
        assert "reason=5" in caplog.text
        assert "Value is incorrect" in caplog.text

    @pytest.mark.parametrize("msg_type", ["A", "0", "1", "2", "4"])
    def test_every_other_admin_message_is_left_to_the_engine(self, app, msg_type: str, caplog) -> None:
        """Heartbeat, TestRequest, ResendRequest and SequenceReset are the
        engine's business. Logging them at WARNING/ERROR would bury the two
        that matter."""
        with caplog.at_level(logging.WARNING, logger="execution.fix_adapter"):
            app.fromAdmin(_FakeMessage({58: "x"}, header={35: msg_type}), "SESSION-1")
        assert caplog.text == ""

    def test_a_headerless_admin_message_is_warned_about_not_raised(self, app, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="execution.fix_adapter"):
            app.fromAdmin(_FakeMessage({}), "SESSION-1")
        assert "error processing admin message" in caplog.text

    def test_no_backend_means_fromadmin_is_inert(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(fa, "fix", None)
        app = _QuickfixApp(on_exec_report=lambda r: None, circuit_breaker=CircuitBreaker())
        app.fromAdmin(_FakeMessage({}, header={35: "5"}), "SESSION-1")


class TestTheSendPathRecordsWhenAnOrderLeft:
    """`toApp` timestamps each ClOrdID; `_handle_exec_report` turns the pair
    into the latency the circuit breaker judges. Lose the timestamp and the
    breaker is fed nothing — it cannot open, whatever the latency."""

    def test_it_timestamps_an_outbound_order(self, app) -> None:
        app.toApp(_FakeMessage({11: "CL-1"}), "SESSION-1")
        assert "CL-1" in app._send_times

    def test_each_order_gets_its_own_timestamp(self, app) -> None:
        app.toApp(_FakeMessage({11: "CL-1"}), "SESSION-1")
        app.toApp(_FakeMessage({11: "CL-2"}), "SESSION-1")
        assert set(app._send_times) == {"CL-1", "CL-2"}

    def test_the_timestamp_is_monotonic_not_wall_clock(self, app) -> None:
        """Wall-clock would make an NTP step look like a latency spike and open
        the breaker on a healthy session."""
        before = time.monotonic()
        app.toApp(_FakeMessage({11: "CL-1"}), "SESSION-1")
        assert before <= app._send_times["CL-1"] <= time.monotonic()


class TestInboundApplicationMessages:
    def test_an_execution_report_is_dispatched(self, app, captured: list[FIXFillReport]) -> None:
        app.fromApp(_exec_report_message(), "SESSION-1")
        assert [r.cl_ord_id for r in captured] == ["CL-1"]

    def test_an_order_cancel_reject_is_dispatched_as_a_rejection(self, app, captured) -> None:
        app.fromApp(_FakeMessage({11: "CL-3", 102: "0", 58: "Too late to cancel"}, header={35: "9"}), "SESSION-1")
        assert captured[0].exec_type is FIXExecType.REJECTED
        assert "Too late to cancel" in captured[0].text

    @pytest.mark.parametrize("msg_type", ["W", "X", "AE", "j"])
    def test_an_unhandled_application_message_dispatches_nothing(self, app, captured, msg_type: str) -> None:
        app.fromApp(_FakeMessage({11: "CL-4"}, header={35: msg_type}), "SESSION-1")
        assert captured == []


class TestExtractingAnExecutionReport:
    def test_every_documented_field_is_read_off_its_own_tag(self, app) -> None:
        """Each assertion pins one tag. A transposed pair — LeavesQty read as
        CumQty, say — is invisible in review and books the wrong position."""
        fields = app._extract_exec_report_fields(
            _FakeMessage(
                {11: "CL-1", 37: "B-1", 150: "1", 55: "XAUUSD", 54: "2", 32: 0.5, 6: 1951.5, 151: 0.5, 14: 0.5}
            )
        )
        assert fields["cl_ord_id"] == "CL-1"
        assert fields["order_id"] == "B-1"
        assert fields["exec_type"] is FIXExecType.PARTIAL_FILL
        assert fields["symbol"] == "XAUUSD"
        assert fields["side"] is FIXSide.SELL
        assert fields["filled_qty"] == 0.5
        assert fields["avg_px"] == 1951.5
        assert fields["leaves_qty"] == 0.5
        assert fields["cum_qty"] == 0.5

    def test_quantities_and_prices_come_back_as_floats(self, app) -> None:
        """The wire carries decimal strings. Everything downstream of here does
        float arithmetic on them — see hopefx-money-precision. What matters at
        this boundary is that the conversion happens exactly once, here."""
        fields = app._extract_exec_report_fields(_exec_report_message(fields={32: "1.0", 6: "1950.25"}))
        assert isinstance(fields["filled_qty"], float)
        assert isinstance(fields["avg_px"], float)
        assert fields["avg_px"] == 1950.25

    @pytest.mark.parametrize(
        ("tag", "name"),
        [
            (11, "ClOrdID"),
            (37, "OrderID"),
            (150, "ExecType"),
            (55, "Symbol"),
            (54, "Side"),
            (32, "LastQty"),
            (6, "AvgPx"),
            (151, "LeavesQty"),
            (14, "CumQty"),
        ],
    )
    def test_each_required_field_is_actually_required(self, app, tag: int, name: str) -> None:
        with pytest.raises(Exception):  # noqa: B017 - the type is the library's, the requirement is ours
            app._extract_exec_report_fields(_exec_report_message(drop=[tag]))

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("0", FIXExecType.NEW),
            ("1", FIXExecType.PARTIAL_FILL),
            ("2", FIXExecType.FILL),
            ("4", FIXExecType.CANCELLED),
            ("8", FIXExecType.REJECTED),
        ],
    )
    def test_every_exec_type_on_the_wire_maps_to_the_enum(self, app, raw: str, expected: FIXExecType) -> None:
        fields = app._extract_exec_report_fields(_exec_report_message(fields={150: raw}))
        assert fields["exec_type"] is expected

    def test_an_exec_type_the_enum_does_not_know_is_refused(self, app, captured) -> None:
        """FIX 4.4 defines more ExecTypes than this enum carries (Replaced,
        Suspended, Expired…). Guessing one would book a fill that never
        happened; refusing it rejects the order and tells the caller."""
        app._handle_exec_report(_exec_report_message(fields={150: "5"}))
        assert captured[0].exec_type is FIXExecType.REJECTED


class TestHandlingAFill:
    def test_the_report_carries_the_wire_values_through(self, app, captured) -> None:
        app._handle_exec_report(_exec_report_message())
        report = captured[0]
        assert (report.cl_ord_id, report.order_id, report.symbol) == ("CL-1", "BROKER-1", "XAUUSD")
        assert report.side is FIXSide.BUY
        assert (report.filled_qty, report.avg_px, report.leaves_qty, report.cum_qty) == (1.0, 1950.25, 0.0, 1.0)

    def test_the_raw_message_is_attached_for_diagnosis(self, app, captured) -> None:
        message = _exec_report_message()
        app._handle_exec_report(message)
        assert captured[0].raw is message

    def test_latency_is_measured_from_the_recorded_send(self, app, captured) -> None:
        app._send_times["CL-1"] = time.monotonic() - 0.25
        app._handle_exec_report(_exec_report_message())
        assert 200.0 < captured[0].latency_ms < 400.0

    def test_a_slow_round_trip_opens_the_circuit_breaker(self, app, captured) -> None:
        """The control this module exists to hold: a degraded session stops
        taking orders rather than continuing to send them."""
        assert not app._cb.is_open
        app._send_times["CL-1"] = time.monotonic() - 0.5  # 500 ms, threshold is 100
        app._handle_exec_report(_exec_report_message())
        assert app._cb.is_open

    def test_a_fast_round_trip_leaves_it_closed(self, app) -> None:
        app._send_times["CL-1"] = time.monotonic()
        app._handle_exec_report(_exec_report_message())
        assert not app._cb.is_open

    def test_the_send_time_is_consumed_not_accumulated(self, app) -> None:
        """`_send_times` grows for the life of the process if entries are read
        rather than popped — one dict entry per order, never freed."""
        app._send_times["CL-1"] = time.monotonic()
        app._handle_exec_report(_exec_report_message())
        assert app._send_times == {}

    def test_an_unsolicited_report_is_dispatched_with_zero_latency(self, app, captured) -> None:
        """No send time means no measurement. Zero is the honest answer; an
        invented one would feed the breaker a number nobody measured."""
        app._handle_exec_report(_exec_report_message())
        assert captured[0].latency_ms == 0.0
        assert not app._cb.is_open

    def test_a_report_with_no_clordid_still_reaches_the_caller(self, app, captured) -> None:
        app._handle_exec_report(_exec_report_message(drop=[11]))
        assert captured[0].cl_ord_id == "<unknown>"
        assert captured[0].exec_type is FIXExecType.REJECTED


class TestHandlingACancelReject:
    def test_the_reason_and_text_reach_the_caller(self, app, captured) -> None:
        app._handle_order_cancel_reject(_FakeMessage({11: "CL-5", 102: "1", 58: "Unknown order"}))
        assert captured[0].cl_ord_id == "CL-5"
        assert "reason=1" in captured[0].text
        assert "Unknown order" in captured[0].text

    def test_it_is_reported_at_error_level(self, app, caplog) -> None:
        with caplog.at_level(logging.ERROR, logger="execution.fix_adapter"):
            app._handle_order_cancel_reject(_FakeMessage({11: "CL-5", 102: "1"}))
        assert "OrderCancelReject" in caplog.text

    def test_a_reject_with_no_clordid_is_logged_and_dispatches_unknown(self, app, captured, caplog) -> None:
        with caplog.at_level(logging.ERROR, logger="execution.fix_adapter"):
            app._handle_order_cancel_reject(_FakeMessage({102: "1"}))
        assert captured == [] or captured[0].cl_ord_id == "<unknown>"


class TestRejectingAPendingOrder:
    def test_the_rejection_is_shaped_like_a_fill_report(self, app, captured) -> None:
        """It travels the same callback as a real fill, so it must be a
        well-formed report — a half-built one raises inside the dispatcher."""
        app._reject_pending("CL-6", RuntimeError("broker said no"))
        report = captured[0]
        assert report.exec_type is FIXExecType.REJECTED
        assert report.cl_ord_id == "CL-6"
        assert report.text == "broker said no"
        assert (report.filled_qty, report.cum_qty, report.leaves_qty, report.avg_px) == (0.0, 0.0, 0.0, 0.0)

    def test_a_rejection_reports_no_fill(self, app, captured) -> None:
        """A non-zero quantity here would book a position out of a refusal."""
        app._reject_pending("CL-6", RuntimeError("x"))
        assert captured[0].filled_qty == 0.0

    def test_a_callback_that_itself_fails_is_warned_about_not_raised(self, fake_fix, caplog) -> None:
        def _explode(report: FIXFillReport) -> None:
            raise RuntimeError("dispatcher is gone")

        app = _QuickfixApp(on_exec_report=_explode, circuit_breaker=CircuitBreaker())
        with caplog.at_level(logging.WARNING, logger="execution.fix_adapter"):
            app._reject_pending("CL-7", ValueError("original"))
        assert "could not dispatch rejection" in caplog.text


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class TestTheCircuitBreaker:
    def test_it_starts_closed(self) -> None:
        assert not CircuitBreaker().is_open

    def test_latency_at_the_threshold_does_not_open_it(self) -> None:
        """The comparison is strictly greater-than. Pinned so the boundary is a
        decision rather than something that drifts by one operator."""
        breaker = CircuitBreaker(threshold_ms=100.0)
        breaker.record_latency(100.0)
        assert not breaker.is_open

    def test_latency_one_step_over_opens_it(self) -> None:
        breaker = CircuitBreaker(threshold_ms=100.0)
        breaker.record_latency(100.1)
        assert breaker.is_open

    def test_check_raises_only_while_open(self) -> None:
        breaker = CircuitBreaker(threshold_ms=100.0)
        breaker.check()
        breaker.record_latency(500.0)
        with pytest.raises(RuntimeError, match="circuit breaker is OPEN"):
            breaker.check()

    def test_a_good_sample_before_the_reset_window_keeps_it_open(self) -> None:
        """One fast reply does not prove the session recovered."""
        breaker = CircuitBreaker(threshold_ms=100.0, reset_after_sec=30.0)
        breaker.record_latency(500.0)
        breaker.record_latency(1.0)
        assert breaker.is_open

    def test_a_good_sample_after_the_reset_window_closes_it(self) -> None:
        breaker = CircuitBreaker(threshold_ms=100.0, reset_after_sec=0.0)
        breaker.record_latency(500.0)
        breaker.record_latency(1.0)
        assert not breaker.is_open

    def test_it_stays_open_while_latency_stays_bad(self) -> None:
        breaker = CircuitBreaker(threshold_ms=100.0, reset_after_sec=0.0)
        breaker.record_latency(500.0)
        breaker.record_latency(500.0)
        assert breaker.is_open

    def test_it_opens_once_not_on_every_sample(self, caplog) -> None:
        breaker = CircuitBreaker(threshold_ms=100.0)
        with caplog.at_level(logging.ERROR, logger="execution.fix_adapter"):
            breaker.record_latency(500.0)
            breaker.record_latency(600.0)
        assert caplog.text.count("circuit_breaker.OPEN") == 1

    def test_concurrent_samples_do_not_corrupt_its_state(self) -> None:
        """It is written from the quickfix reader thread and read from the
        event loop."""
        breaker = CircuitBreaker(threshold_ms=100.0)
        threads = [threading.Thread(target=breaker.record_latency, args=(500.0,)) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert breaker.is_open


# ---------------------------------------------------------------------------
# Credential validation
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FIX_SENDER_COMP_ID", "FIX_TARGET_COMP_ID", "FIX_HOST", "FIX_PORT", "APP_ENV"):
        monkeypatch.delenv(name, raising=False)


def _real_adapter(**kwargs: Any) -> FIXAdapter:
    defaults = {"sender_comp_id": "HOPEFX-PROD", "target_comp_id": "IBFX", "host": "fix.broker.example"}
    defaults.update(kwargs)
    return FIXAdapter(**defaults)  # type: ignore[arg-type]


class TestPlaceholderCredentialsAreRefused:
    """A session that logs on with `SenderCompID=CLIENT` does not log on. The
    check exists so that failure surfaces at startup rather than on the first
    order."""

    def test_real_looking_values_pass(self, clean_env) -> None:
        assert _real_adapter().validate_credentials() is True

    @pytest.mark.parametrize("placeholder", ["CLIENT", "BROKER", "HOPEFX", "CHANGE_ME", ""])
    def test_a_placeholder_sender_fails(self, clean_env, placeholder: str) -> None:
        assert _real_adapter(sender_comp_id=placeholder).validate_credentials() is False

    @pytest.mark.parametrize("placeholder", ["CLIENT", "BROKER", "HOPEFX", "CHANGE_ME", ""])
    def test_a_placeholder_target_fails(self, clean_env, placeholder: str) -> None:
        assert _real_adapter(target_comp_id=placeholder).validate_credentials() is False

    @pytest.mark.parametrize("placeholder", ["", "<CHANGE_ME_BROKER_FIX_HOST>", "<CHANGE_ME_anything>"])
    def test_a_placeholder_host_fails(self, clean_env, placeholder: str) -> None:
        assert _real_adapter(host=placeholder).validate_credentials() is False

    def test_the_default_constructor_is_a_placeholder_by_design(self, clean_env) -> None:
        """`FIXAdapter()` cannot reach a broker, and says so. A default that
        validated would be a default that looked configured."""
        assert FIXAdapter().validate_credentials() is False

    def test_the_environment_overrides_the_constructor(self, clean_env, monkeypatch) -> None:
        monkeypatch.setenv("FIX_SENDER_COMP_ID", "HOPEFX-PROD")
        monkeypatch.setenv("FIX_TARGET_COMP_ID", "IBFX")
        monkeypatch.setenv("FIX_HOST", "fix.broker.example")
        assert FIXAdapter().validate_credentials() is True

    def test_the_environment_can_also_reintroduce_a_placeholder(self, clean_env, monkeypatch) -> None:
        monkeypatch.setenv("FIX_SENDER_COMP_ID", "CLIENT")
        assert _real_adapter().validate_credentials() is False

    def test_the_default_host_is_real_even_though_the_comp_ids_are_not(self, clean_env, caplog) -> None:
        """`FIXAdapter()` defaults to 127.0.0.1, which is a real host — a local
        FIX simulator is a supported setup. So the default fails on two counts,
        not three, and the host check needs an explicitly empty value to fire."""
        with caplog.at_level(logging.CRITICAL, logger="execution.fix_adapter"):
            FIXAdapter().validate_credentials()
        assert caplog.text.count("credential error") == 2
        assert "FIX_HOST" not in caplog.text

    def test_each_failure_is_logged_at_critical(self, clean_env, caplog) -> None:
        with caplog.at_level(logging.CRITICAL, logger="execution.fix_adapter"):
            FIXAdapter(host="").validate_credentials()
        assert caplog.text.count("credential error") == 3

    def test_raise_on_error_names_every_problem_at_once(self, clean_env) -> None:
        """One round trip per misconfiguration is how a deployment takes three
        attempts instead of one."""
        with pytest.raises(RuntimeError) as excinfo:
            FIXAdapter(host="").validate_credentials(raise_on_error=True)
        message = str(excinfo.value)
        assert "FIX_SENDER_COMP_ID" in message
        assert "FIX_TARGET_COMP_ID" in message
        assert "FIX_HOST" in message

    def test_raise_on_error_is_silent_when_everything_is_real(self, clean_env) -> None:
        assert _real_adapter().validate_credentials(raise_on_error=True) is True


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestStartingAndStopping:
    def test_production_refuses_to_start_on_placeholders(self, clean_env, monkeypatch) -> None:
        """`APP_ENV` defaults to production, so an unset environment is the
        strict one. Getting that default backwards would let a misconfigured
        session start and fail later, on an order."""
        adapter = FIXAdapter()
        with pytest.raises(RuntimeError, match="placeholder credentials"):
            adapter.start()
        assert adapter._running is False

    def test_a_non_production_environment_starts_anyway(self, clean_env, monkeypatch) -> None:
        """Paper trading and CI have no broker credentials and must still run."""
        monkeypatch.setenv("APP_ENV", "development")
        adapter = FIXAdapter()
        adapter.HEARTBEAT_INTERVAL = 0.01  # type: ignore[misc]
        try:
            adapter.start()
            assert adapter._running is True
        finally:
            adapter.stop()

    def test_simulation_mode_says_so(self, clean_env, monkeypatch, caplog) -> None:
        monkeypatch.setenv("APP_ENV", "development")
        adapter = FIXAdapter()
        adapter.HEARTBEAT_INTERVAL = 0.01  # type: ignore[misc]
        with caplog.at_level(logging.WARNING, logger="execution.fix_adapter"):
            try:
                adapter.start()
            finally:
                adapter.stop()
        assert "no FIX backend available" in caplog.text

    def test_the_heartbeat_thread_is_a_daemon(self, clean_env, monkeypatch) -> None:
        """A non-daemon heartbeat keeps the process alive after shutdown."""
        monkeypatch.setenv("APP_ENV", "development")
        adapter = FIXAdapter()
        adapter.HEARTBEAT_INTERVAL = 0.01  # type: ignore[misc]
        try:
            adapter.start()
            assert adapter._hb_thread is not None
            assert adapter._hb_thread.daemon
        finally:
            adapter.stop()

    def test_stop_ends_the_heartbeat_promptly(self, clean_env, monkeypatch) -> None:
        """`stop()` must interrupt the interval rather than wait it out — the
        reason the loop uses `Event.wait` and not `time.sleep`."""
        monkeypatch.setenv("APP_ENV", "development")
        adapter = FIXAdapter()
        adapter.HEARTBEAT_INTERVAL = 30  # type: ignore[misc]
        adapter.start()
        thread = adapter._hb_thread
        assert thread is not None
        adapter.stop()
        thread.join(timeout=5.0)
        assert not thread.is_alive(), "stop() did not interrupt the heartbeat interval"

    def test_the_heartbeat_reports_the_breaker_state(self, clean_env, caplog) -> None:
        """The heartbeat is the only place an operator sees the breaker without
        an order being refused. A heartbeat that always printed CLOSED would be
        a status line that cannot report the one status worth reporting."""
        adapter = FIXAdapter()
        adapter.HEARTBEAT_INTERVAL = 0.01  # type: ignore[misc]
        adapter.circuit_breaker.record_latency(500.0)
        adapter._running = True
        thread = threading.Thread(target=adapter._heartbeat_loop, daemon=True)
        with caplog.at_level(logging.DEBUG, logger="execution.fix_adapter"):
            try:
                thread.start()
                deadline = time.monotonic() + 5.0
                while "fix_adapter.heartbeat" not in caplog.text and time.monotonic() < deadline:
                    time.sleep(0.01)
            finally:
                adapter._running = False
                if adapter._hb_stop_event is not None:
                    adapter._hb_stop_event.set()
                thread.join(timeout=5.0)
        assert "circuit=OPEN" in caplog.text

    def test_stop_is_safe_before_start(self) -> None:
        FIXAdapter().stop()

    def test_stop_is_idempotent(self, clean_env, monkeypatch) -> None:
        monkeypatch.setenv("APP_ENV", "development")
        adapter = FIXAdapter()
        adapter.HEARTBEAT_INTERVAL = 0.01  # type: ignore[misc]
        adapter.start()
        adapter.stop()
        adapter.stop()
        assert adapter._running is False

    def test_a_failing_initiator_does_not_stop_the_rest_of_shutdown(self, caplog) -> None:
        """`stop()` must always complete: the heartbeat thread and the pending
        futures are cleaned up after this point."""

        class _BadInitiator:
            def stop(self) -> None:
                raise ConnectionError("socket already gone")

        adapter = FIXAdapter()
        adapter._initiator = _BadInitiator()
        adapter._running = True
        with caplog.at_level(logging.ERROR, logger="execution.fix_adapter"):
            adapter.stop()
        assert adapter._running is False
        assert "initiator.stop() raised" in caplog.text

    def test_stop_closes_the_session(self) -> None:
        adapter = FIXAdapter()
        initiator = _FakeInitiator(None, None, None, None)
        adapter._initiator = initiator
        adapter.stop()
        assert initiator.stopped


# ---------------------------------------------------------------------------
# quickfix session bring-up
# ---------------------------------------------------------------------------


class TestBringingUpAQuickfixSession:
    def test_an_existing_config_file_is_used_as_written(self, fake_fix, tmp_path: pathlib.Path) -> None:
        """An operator-supplied fix.cfg carries the store path, the schedule and
        the reset flags. Regenerating over it would silently discard all of them
        — including the sequence-number store."""
        cfg = tmp_path / "fix.cfg"
        cfg.write_text("[DEFAULT]\nConnectionType=initiator\nFileStorePath=/var/lib/hopefx/fix_store\n")
        adapter = FIXAdapter(config_file=str(cfg))
        adapter._start_quickfix()
        assert adapter._initiator.settings.path == str(cfg)
        assert "/var/lib/hopefx/fix_store" in adapter._initiator.settings.text

    def test_a_missing_config_file_is_generated_from_the_constructor(self, fake_fix, tmp_path) -> None:
        adapter = FIXAdapter(
            config_file=str(tmp_path / "absent.cfg"),
            sender_comp_id="HOPEFX-PROD",
            target_comp_id="IBFX",
            host="fix.broker.example",
            port=4002,
        )
        adapter._start_quickfix()
        text = adapter._initiator.settings.text
        assert "BeginString=FIX.4.4" in text
        assert "SenderCompID=HOPEFX-PROD" in text
        assert "TargetCompID=IBFX" in text
        assert "SocketConnectHost=fix.broker.example" in text
        assert "SocketConnectPort=4002" in text
        assert "ConnectionType=initiator" in text

    def test_the_generated_config_carries_the_declared_heartbeat(self, fake_fix, tmp_path) -> None:
        adapter = FIXAdapter(config_file=str(tmp_path / "absent.cfg"))
        adapter._start_quickfix()
        assert f"HeartBtInt={FIXAdapter.HEARTBEAT_INTERVAL}" in adapter._initiator.settings.text

    def test_the_generated_config_file_is_removed(self, fake_fix, tmp_path) -> None:
        """It carries SenderCompID and the session identity into the system temp
        directory. Leaving it there leaves that readable."""
        adapter = FIXAdapter(config_file=str(tmp_path / "absent.cfg"))
        adapter._start_quickfix()
        assert not pathlib.Path(adapter._initiator.settings.path).exists()

    def test_the_application_is_wired_to_the_adapters_own_dispatcher(self, fake_fix, tmp_path) -> None:
        """The callback identity is the whole integration: an app wired to
        anything else would log fills and resolve no futures."""
        adapter = FIXAdapter(config_file=str(tmp_path / "absent.cfg"))
        adapter._start_quickfix()
        assert adapter._app is not None
        assert adapter._app._on_exec_report == adapter._dispatch_exec_report
        assert adapter._app._cb is adapter.circuit_breaker

    def test_credentials_reach_the_application(self, fake_fix, tmp_path) -> None:
        adapter = FIXAdapter(config_file=str(tmp_path / "absent.cfg"), username="u", password=TEST_PASSWORD)
        adapter._start_quickfix()
        assert (adapter._app._username, adapter._app._password) == ("u", TEST_PASSWORD)

    def test_the_initiator_is_started(self, fake_fix, tmp_path) -> None:
        adapter = FIXAdapter(config_file=str(tmp_path / "absent.cfg"))
        adapter._start_quickfix()
        assert adapter._initiator.started

    def test_the_first_session_id_is_captured(self, fake_fix, tmp_path) -> None:
        """`_send_quickfix` refuses to send without one."""
        adapter = FIXAdapter(config_file=str(tmp_path / "absent.cfg"))
        adapter._start_quickfix()
        assert adapter._session_id == "SESSION-1"

    def test_no_sessions_leaves_the_session_id_unset(self, fake_fix, tmp_path, monkeypatch) -> None:
        class _NoSessions(_FakeInitiator):
            def getSessions(self):
                return []

        monkeypatch.setattr(fake_fix.fix, "SocketInitiator", _NoSessions)
        adapter = FIXAdapter(config_file=str(tmp_path / "absent.cfg"))
        adapter._start_quickfix()
        assert adapter._session_id is None


class TestSendingAnOrderOverQuickfix:
    @pytest.fixture
    def started(self, fake_fix, tmp_path) -> FIXAdapter:
        adapter = FIXAdapter(config_file=str(tmp_path / "absent.cfg"))
        adapter._start_quickfix()
        return adapter

    def test_no_session_means_no_send(self, fake_fix) -> None:
        """Sending before logon must fail loudly, not quietly drop the order."""
        adapter = FIXAdapter()
        with pytest.raises(RuntimeError, match="session not established"):
            adapter._send_quickfix(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0))

    def test_a_market_order_carries_the_required_tags(self, started, fake_fix) -> None:
        started._send_quickfix(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.5, cl_ord_id="CL-1"))
        message, session_id = fake_fix.sent[0]
        assert session_id == "SESSION-1"
        assert message.fields[11] == "CL-1"
        assert message.fields[55] == "XAUUSD"
        assert message.fields[54] == "1"
        assert message.fields[40] == "1"
        assert message.fields[38] == 1.5
        assert message.fields[59] == "0"
        assert 60 in message.fields, "TransactTime is required on NewOrderSingle"

    def test_the_header_declares_fix_44(self, started, fake_fix) -> None:
        started._send_quickfix(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0))
        assert fake_fix.sent[0][0].getHeader().fields[8] == "FIX.4.4"

    def test_a_sell_is_side_two(self, started, fake_fix) -> None:
        """Transposing 1 and 2 opens the opposite position at full size."""
        started._send_quickfix(FIXOrder(symbol="XAUUSD", side=FIXSide.SELL, quantity=1.0))
        assert fake_fix.sent[0][0].fields[54] == "2"

    def test_a_limit_order_carries_its_price(self, started, fake_fix) -> None:
        started._send_quickfix(
            FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, ord_type=FIXOrdType.LIMIT, price=1950.25)
        )
        assert fake_fix.sent[0][0].fields[44] == 1950.25

    def test_a_limit_order_with_no_price_sends_no_price_tag(self, started, fake_fix) -> None:
        """Tag 44 defaulted to zero would be a limit to buy at nothing, or to
        sell at nothing — either way an order the broker may accept."""
        started._send_quickfix(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, ord_type=FIXOrdType.LIMIT))
        assert 44 not in fake_fix.sent[0][0].fields

    def test_a_stop_order_carries_its_stop_price(self, started, fake_fix) -> None:
        started._send_quickfix(
            FIXOrder(symbol="XAUUSD", side=FIXSide.SELL, quantity=1.0, ord_type=FIXOrdType.STOP, stop_px=1900.0)
        )
        assert fake_fix.sent[0][0].fields[99] == 1900.0

    def test_a_market_order_carries_neither_price_nor_stop(self, started, fake_fix) -> None:
        started._send_quickfix(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, price=1950.0, stop_px=1900.0))
        message = fake_fix.sent[0][0]
        assert 44 not in message.fields and 99 not in message.fields

    def test_an_account_is_sent_when_set_and_omitted_when_not(self, started, fake_fix) -> None:
        started._send_quickfix(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, account="DU123456"))
        assert fake_fix.sent[0][0].fields[1] == "DU123456"
        started._send_quickfix(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0))
        assert 1 not in fake_fix.sent[1][0].fields

    @pytest.mark.parametrize("tif", ["0", "1", "3", "4"])
    def test_the_time_in_force_is_passed_through(self, started, fake_fix, tif: str) -> None:
        started._send_quickfix(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, time_in_force=tif))
        assert fake_fix.sent[0][0].fields[59] == tif


# ---------------------------------------------------------------------------
# The pyfixmsg wire format
# ---------------------------------------------------------------------------


def _fields_of(raw: bytes) -> dict[str, str]:
    """Every tag=value pair in a raw FIX message, in dict form."""
    return {part.split("=", 1)[0]: part.split("=", 1)[1] for part in raw.decode().split(SOH) if "=" in part}


def _tags_in_order(raw: bytes) -> list[str]:
    return [part.split("=", 1)[0] for part in raw.decode().split(SOH) if "=" in part]


def _assert_well_framed(raw: bytes) -> None:
    """Check BodyLength and CheckSum against FIX 4.4's own definitions.

    BodyLength (9) counts the bytes after the BodyLength field's own delimiter
    up to and including the delimiter before the CheckSum field. CheckSum (10)
    is the sum of every byte before it, modulo 256, as three digits. Both are
    recomputed here from the emitted bytes, so a message assembled out of the
    wrong pieces fails even though the code computed its own numbers happily.
    """
    text = raw.decode()
    assert text.startswith("8=FIX.4.4" + SOH), "BeginString must be the first field"
    body_start = text.index(SOH, text.index("9=")) + 1
    checksum_start = text.rindex(SOH + "10=") + 1
    declared_len = int(text[text.index("9=") + 2 : body_start - 1])
    assert declared_len == len(text[body_start:checksum_start].encode()), "BodyLength does not match the body"

    checksum_field = text[checksum_start:]
    assert checksum_field.startswith("10=") and checksum_field.endswith(SOH)
    assert len(checksum_field) == len("10=000") + 1, "CheckSum must be exactly three digits"
    assert int(checksum_field[3:6]) == sum(text[:checksum_start].encode()) % 256


class TestTheLogonMessageOnTheWire:
    @pytest.fixture
    def adapter(self) -> FIXAdapter:
        return FIXAdapter(sender_comp_id="HOPEFX-PROD", target_comp_id="IBFX")

    def test_it_is_a_well_framed_fix_44_message(self, adapter) -> None:
        _assert_well_framed(adapter._build_pyfixmsg_logon())

    def test_the_first_three_tags_are_in_the_order_fix_requires(self, adapter) -> None:
        """BeginString, BodyLength, MsgType must lead, in that order. A counterparty
        rejects the session outright otherwise."""
        assert _tags_in_order(adapter._build_pyfixmsg_logon())[:3] == ["8", "9", "35"]

    def test_it_identifies_both_sides_and_asks_for_a_heartbeat(self, adapter) -> None:
        fields = _fields_of(adapter._build_pyfixmsg_logon())
        assert fields["35"] == "A"
        assert fields["49"] == "HOPEFX-PROD"
        assert fields["56"] == "IBFX"
        assert fields["98"] == "0"
        assert fields["108"] == "30"

    def test_the_sending_time_is_utc_in_fix_format(self, adapter) -> None:
        """A local-time SendingTime is rejected as outside the permitted window
        by any counterparty more than a couple of minutes away from you."""
        sending_time = _fields_of(adapter._build_pyfixmsg_logon())["52"]
        parsed = time.strptime(sending_time, "%Y%m%d-%H:%M:%S")
        assert abs(time.mktime(parsed) - time.mktime(time.gmtime())) < 120

    def test_credentials_are_sent_only_when_configured(self) -> None:
        bare = _fields_of(FIXAdapter()._build_pyfixmsg_logon())
        assert "553" not in bare and "554" not in bare
        with_creds = _fields_of(FIXAdapter(username="u", password=TEST_PASSWORD)._build_pyfixmsg_logon())
        assert with_creds["553"] == "u"
        assert with_creds["554"] == TEST_PASSWORD

    def test_the_sequence_number_starts_where_the_session_does(self, adapter) -> None:
        assert _fields_of(adapter._build_pyfixmsg_logon())["34"] == "1"

    def test_the_sequence_number_advances_once_per_message(self, adapter) -> None:
        """Reusing a MsgSeqNum is a session-level Reject; skipping one triggers
        a ResendRequest. Neither is recoverable without operator action."""
        seqs = [int(_fields_of(adapter._build_pyfixmsg_logon())["34"]) for _ in range(4)]
        assert seqs == [1, 2, 3, 4]


class TestTheNewOrderSingleOnTheWire:
    @pytest.fixture
    def connected(self, monkeypatch: pytest.MonkeyPatch) -> tuple[FIXAdapter, list[bytes]]:
        adapter = FIXAdapter(sender_comp_id="HOPEFX-PROD", target_comp_id="IBFX")
        sent: list[bytes] = []
        adapter._pyfixmsg_sock = types.SimpleNamespace(sendall=sent.append)
        return adapter, sent

    def test_an_unconnected_socket_refuses_the_order(self) -> None:
        adapter = FIXAdapter()
        with pytest.raises(RuntimeError, match="socket not connected"):
            adapter._send_pyfixmsg(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0))

    def test_it_is_a_well_framed_fix_44_message(self, connected) -> None:
        adapter, sent = connected
        adapter._send_pyfixmsg(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0))
        _assert_well_framed(sent[0])

    def test_it_carries_the_tags_a_new_order_single_requires(self, connected) -> None:
        adapter, sent = connected
        adapter._send_pyfixmsg(
            FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.5, cl_ord_id="CL-1", time_in_force="3")
        )
        fields = _fields_of(sent[0])
        assert fields["35"] == "D"
        assert fields["11"] == "CL-1"
        assert fields["55"] == "XAUUSD"
        assert fields["54"] == "1"
        assert fields["40"] == "1"
        assert fields["38"] == "1.5"
        assert fields["59"] == "3"
        assert fields["60"] == fields["52"]

    def test_a_sell_is_side_two(self, connected) -> None:
        adapter, sent = connected
        adapter._send_pyfixmsg(FIXOrder(symbol="XAUUSD", side=FIXSide.SELL, quantity=1.0))
        assert _fields_of(sent[0])["54"] == "2"

    def test_a_limit_carries_price_and_a_market_does_not(self, connected) -> None:
        adapter, sent = connected
        adapter._send_pyfixmsg(
            FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, ord_type=FIXOrdType.LIMIT, price=1950.25)
        )
        assert _fields_of(sent[0])["44"] == "1950.25"
        adapter._send_pyfixmsg(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, price=1950.25))
        assert "44" not in _fields_of(sent[1])

    def test_a_stop_carries_stoppx(self, connected) -> None:
        adapter, sent = connected
        adapter._send_pyfixmsg(
            FIXOrder(symbol="XAUUSD", side=FIXSide.SELL, quantity=1.0, ord_type=FIXOrdType.STOP, stop_px=1900.0)
        )
        assert _fields_of(sent[0])["99"] == "1900.0"

    def test_the_account_and_currency_are_sent_when_set(self, connected) -> None:
        adapter, sent = connected
        adapter._send_pyfixmsg(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, account="DU1", currency="USD"))
        fields = _fields_of(sent[0])
        assert fields["1"] == "DU1"
        assert fields["15"] == "USD"

    def test_an_empty_account_or_currency_sends_no_tag(self, connected) -> None:
        adapter, sent = connected
        adapter._send_pyfixmsg(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, currency=""))
        fields = _fields_of(sent[0])
        assert "1" not in fields and "15" not in fields

    def test_the_sequence_number_advances_with_every_order(self, connected) -> None:
        adapter, sent = connected
        for _ in range(3):
            adapter._send_pyfixmsg(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0))
        assert [_fields_of(raw)["34"] for raw in sent] == ["1", "2", "3"]

    @pytest.mark.parametrize("quantity", [0.01, 0.1, 1.0, 1.5, 10.0, 100.0, 12345.67])
    def test_a_realistic_quantity_is_a_plain_decimal_string(self, connected, quantity: float) -> None:
        """FIX carries quantities as decimal strings. `str(float)` is the
        conversion used here, and for every size this platform trades it
        produces a plain decimal — see the boundary test below for where that
        stops being true."""
        adapter, sent = connected
        adapter._send_pyfixmsg(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=quantity))
        on_the_wire = _fields_of(sent[0])["38"]
        assert "e" not in on_the_wire.lower()
        assert float(on_the_wire) == quantity

    def test_a_sub_micro_quantity_leaves_as_scientific_notation(self, connected) -> None:
        """Pinned, not endorsed. `str(1e-07)` is "1e-07", which is not a valid
        FIX Qty — the counterparty rejects it. Nothing upstream can produce a
        size this small (`risk/manager.py` floors lot sizes far above it), so
        this is a boundary of the float representation rather than a live
        defect. It is recorded here so that a future change which *can* reach
        it finds a test rather than a broker reject."""
        adapter, sent = connected
        adapter._send_pyfixmsg(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1e-07))
        assert _fields_of(sent[0])["38"] == "1e-07"

    def test_a_failed_send_is_raised_not_swallowed(self, monkeypatch) -> None:
        """A dropped order that reports success is worse than one that fails:
        the OMS books a position the broker never saw."""

        def _broken(payload: bytes) -> None:
            raise OSError("broken pipe")

        adapter = FIXAdapter()
        adapter._pyfixmsg_sock = types.SimpleNamespace(sendall=_broken)
        with pytest.raises(RuntimeError, match="send failed"):
            adapter._send_pyfixmsg(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, cl_ord_id="CL-1"))

    def test_the_send_is_recorded_for_latency_when_an_application_exists(self, connected, fake_fix, tmp_path) -> None:
        adapter, sent = connected
        adapter._app = _QuickfixApp(on_exec_report=lambda r: None, circuit_breaker=adapter.circuit_breaker)
        adapter._send_pyfixmsg(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, cl_ord_id="CL-1"))
        assert "CL-1" in adapter._app._send_times

    def test_the_pyfixmsg_path_measures_no_latency_of_its_own(self, connected) -> None:
        """A finding, pinned rather than fixed.

        `_send_pyfixmsg` records its send time on `self._app`, and `_app` is
        only ever constructed by `_start_quickfix`. Start the pyfixmsg backend
        and `_app` stays None, so no send time is recorded; `_handle_pyfixmsg_message`
        builds every report with the default `latency_ms=0.0` and never calls
        `record_latency`. The circuit breaker therefore cannot open on that
        backend, whatever the round trip — the comment on the line claims it
        "mirrors quickfix path", and it does not.

        It is dormant rather than live: `requirements.txt:186` records that
        pyfixmsg was removed because it is unavailable for Python 3.12, so
        production runs quickfix. Raised for the owner rather than changed
        here, because making a circuit breaker live on a money path is not a
        side effect of a coverage task.
        """
        adapter, sent = connected
        assert adapter._app is None
        adapter._send_pyfixmsg(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, cl_ord_id="CL-1"))
        adapter._handle_pyfixmsg_message(
            (
                f"8=FIX.4.4{SOH}35=8{SOH}11=CL-1{SOH}150=2{SOH}55=XAUUSD{SOH}54=1{SOH}"
                f"32=1{SOH}6=1950{SOH}151=0{SOH}14=1{SOH}10=000{SOH}"
            ).encode()
        )
        assert not adapter.circuit_breaker.is_open


# ---------------------------------------------------------------------------
# pyfixmsg session bring-up and inbound framing
# ---------------------------------------------------------------------------


class _FakeSocket:
    """A socket that hands back scripted chunks and records what was sent."""

    def __init__(self, family: Any = None, kind: Any = None) -> None:
        self.family = family
        self.kind = kind
        self.timeouts: list[float | None] = []
        self.connected_to: tuple[str, int] | None = None
        self.sent: list[bytes] = []
        self.chunks: list[bytes] = []
        self.connect_error: OSError | None = None
        self.recv_error: OSError | None = None
        self.closed = False

    def settimeout(self, value: float | None) -> None:
        self.timeouts.append(value)

    def connect(self, address: tuple[str, int]) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.connected_to = address

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)

    def recv(self, size: int) -> bytes:
        if self.recv_error is not None:
            raise self.recv_error
        return self.chunks.pop(0) if self.chunks else b""

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_socket(monkeypatch: pytest.MonkeyPatch) -> _FakeSocket:
    sock = _FakeSocket()
    monkeypatch.setattr("socket.socket", lambda family, kind: sock)
    monkeypatch.setattr(fa, "pyfixmsg", types.SimpleNamespace())
    monkeypatch.setattr(fa, "FixMessage", type("FixMessage", (), {}))
    return sock


class TestBringingUpAPyfixmsgSession:
    def test_a_missing_library_is_refused_before_the_socket_is_opened(self, monkeypatch) -> None:
        monkeypatch.setattr(fa, "pyfixmsg", None)
        with pytest.raises(RuntimeError, match="pyfixmsg is not installed"):
            FIXAdapter()._start_pyfixmsg()

    def test_it_connects_to_the_configured_endpoint(self, fake_socket) -> None:
        adapter = FIXAdapter(host="fix.broker.example", port=4002)
        adapter._start_pyfixmsg()
        assert fake_socket.connected_to == ("fix.broker.example", 4002)

    def test_the_connect_is_bounded_then_the_reader_blocks(self, fake_socket) -> None:
        """A blocking connect with no timeout hangs startup indefinitely; a
        timeout left on afterwards would make the reader spin on socket.timeout."""
        FIXAdapter()._start_pyfixmsg()
        assert fake_socket.timeouts == [10.0, None]

    def test_a_refused_connection_names_the_endpoint(self, fake_socket) -> None:
        fake_socket.connect_error = ConnectionRefusedError("nobody listening")
        adapter = FIXAdapter(host="fix.broker.example", port=4002)
        with pytest.raises(RuntimeError, match="cannot connect to fix.broker.example:4002"):
            adapter._start_pyfixmsg()

    def test_a_logon_is_sent_immediately(self, fake_socket) -> None:
        adapter = FIXAdapter(sender_comp_id="HOPEFX-PROD", target_comp_id="IBFX")
        adapter._start_pyfixmsg()
        assert len(fake_socket.sent) == 1
        assert _fields_of(fake_socket.sent[0])["35"] == "A"

    def test_the_socket_is_kept_for_the_send_path(self, fake_socket) -> None:
        adapter = FIXAdapter()
        adapter._start_pyfixmsg()
        assert adapter._pyfixmsg_sock is fake_socket

    def test_the_sequence_counter_is_reset_for_the_new_session(self, fake_socket) -> None:
        """A reconnect that carried the old counter forward would log on with a
        MsgSeqNum the counterparty has already seen."""
        adapter = FIXAdapter()
        adapter._pyfixmsg_seq = 97
        adapter._start_pyfixmsg()
        assert _fields_of(fake_socket.sent[0])["34"] == "1"
        assert adapter._pyfixmsg_seq == 2

    def test_the_reader_thread_is_a_daemon(self, fake_socket) -> None:
        adapter = FIXAdapter()
        before = {t.name for t in threading.enumerate()}
        adapter._start_pyfixmsg()
        readers = [t for t in threading.enumerate() if t.name == "FIXpyfixmsgReader" and t.name not in before]
        for thread in readers:
            assert thread.daemon
            thread.join(timeout=5.0)


class TestReadingFromTheWire:
    def _drain(self, adapter: FIXAdapter, sock: _FakeSocket) -> None:
        adapter._running = True
        adapter._pyfixmsg_reader_loop(sock)

    def test_a_whole_message_in_one_chunk_is_dispatched(self, monkeypatch) -> None:
        adapter = FIXAdapter()
        seen: list[bytes] = []
        monkeypatch.setattr(adapter, "_handle_pyfixmsg_message", seen.append)
        sock = _FakeSocket()
        sock.chunks = [f"8=FIX.4.4{SOH}35=0{SOH}10=123{SOH}".encode()]
        self._drain(adapter, sock)
        assert len(seen) == 1

    def test_two_messages_in_one_chunk_are_both_dispatched(self, monkeypatch) -> None:
        """TCP does not preserve message boundaries. A reader that assumed one
        recv is one message would drop every fill that arrived in a burst."""
        adapter = FIXAdapter()
        seen: list[bytes] = []
        monkeypatch.setattr(adapter, "_handle_pyfixmsg_message", seen.append)
        sock = _FakeSocket()
        one = f"8=FIX.4.4{SOH}35=0{SOH}10=123{SOH}".encode()
        sock.chunks = [one + one]
        self._drain(adapter, sock)
        assert len(seen) == 2

    def test_a_message_split_across_chunks_is_reassembled(self, monkeypatch) -> None:
        adapter = FIXAdapter()
        seen: list[bytes] = []
        monkeypatch.setattr(adapter, "_handle_pyfixmsg_message", seen.append)
        sock = _FakeSocket()
        whole = f"8=FIX.4.4{SOH}35=8{SOH}11=CL-1{SOH}10=123{SOH}".encode()
        sock.chunks = [whole[:10], whole[10:]]
        self._drain(adapter, sock)
        assert len(seen) == 1
        assert seen[0] == whole

    def test_a_partial_trailer_waits_for_the_rest(self, monkeypatch) -> None:
        adapter = FIXAdapter()
        seen: list[bytes] = []
        monkeypatch.setattr(adapter, "_handle_pyfixmsg_message", seen.append)
        sock = _FakeSocket()
        sock.chunks = [f"8=FIX.4.4{SOH}35=0{SOH}10=12".encode()]
        self._drain(adapter, sock)
        assert seen == []

    def test_a_closed_connection_ends_the_loop(self, caplog) -> None:
        adapter = FIXAdapter()
        sock = _FakeSocket()
        with caplog.at_level(logging.WARNING, logger="execution.fix_adapter"):
            self._drain(adapter, sock)
        assert "connection closed by peer" in caplog.text

    def test_a_socket_error_while_running_is_reported(self, caplog) -> None:
        adapter = FIXAdapter()
        sock = _FakeSocket()
        sock.recv_error = OSError("connection reset by peer")
        with caplog.at_level(logging.ERROR, logger="execution.fix_adapter"):
            self._drain(adapter, sock)
        assert "socket error" in caplog.text

    def test_a_socket_error_during_shutdown_is_not_reported(self, caplog) -> None:
        """`stop()` closes the socket under the reader. An ERROR for every
        ordinary shutdown trains operators to ignore the channel."""
        adapter = FIXAdapter()
        sock = _FakeSocket()
        sock.recv_error = OSError("bad file descriptor")

        class _StoppingSocket(_FakeSocket):
            def recv(self, size: int) -> bytes:
                adapter._running = False
                raise OSError("bad file descriptor")

        with caplog.at_level(logging.ERROR, logger="execution.fix_adapter"):
            adapter._running = True
            adapter._pyfixmsg_reader_loop(_StoppingSocket())
        assert "socket error" not in caplog.text

    def test_a_stopped_adapter_reads_nothing(self) -> None:
        adapter = FIXAdapter()
        sock = _FakeSocket()
        sock.chunks = [f"8=FIX.4.4{SOH}35=0{SOH}10=123{SOH}".encode()]
        adapter._running = False
        adapter._pyfixmsg_reader_loop(sock)
        assert sock.chunks, "a stopped reader must not consume from the socket"


def _raw_exec_report(**overrides: str) -> bytes:
    fields = {
        "35": "8",
        "11": "CL-1",
        "37": "B-1",
        "150": "2",
        "55": "XAUUSD",
        "54": "1",
        "32": "1.5",
        "6": "1950.25",
        "151": "0",
        "14": "1.5",
        "58": "",
    }
    fields.update(overrides)
    body = SOH.join(f"{tag}={value}" for tag, value in fields.items())
    return f"8=FIX.4.4{SOH}{body}{SOH}10=000{SOH}".encode()


class TestParsingAnInboundMessage:
    @pytest.fixture
    def adapter(self) -> FIXAdapter:
        return FIXAdapter()

    def _dispatched(self, adapter: FIXAdapter, monkeypatch) -> list[FIXFillReport]:
        seen: list[FIXFillReport] = []
        monkeypatch.setattr(adapter, "_dispatch_exec_report", seen.append)
        return seen

    def test_an_execution_report_is_read_off_the_right_tags(self, adapter, monkeypatch) -> None:
        seen = self._dispatched(adapter, monkeypatch)
        adapter._handle_pyfixmsg_message(_raw_exec_report())
        report = seen[0]
        assert report.cl_ord_id == "CL-1"
        assert report.order_id == "B-1"
        assert report.exec_type is FIXExecType.FILL
        assert report.symbol == "XAUUSD"
        assert report.side is FIXSide.BUY
        assert (report.filled_qty, report.avg_px, report.leaves_qty, report.cum_qty) == (1.5, 1950.25, 0.0, 1.5)

    def test_the_parsed_fields_are_kept_for_diagnosis(self, adapter, monkeypatch) -> None:
        seen = self._dispatched(adapter, monkeypatch)
        adapter._handle_pyfixmsg_message(_raw_exec_report())
        assert seen[0].raw["55"] == "XAUUSD"

    def test_an_unknown_exec_type_is_read_as_new_rather_than_a_fill(self, adapter, monkeypatch) -> None:
        """FIX 4.4 has ExecTypes this enum does not carry. Falling back to NEW
        reports "acknowledged, nothing filled" — the safe reading. Falling back
        to FILL would book a position out of a status message."""
        seen = self._dispatched(adapter, monkeypatch)
        adapter._handle_pyfixmsg_message(_raw_exec_report(**{"150": "E"}))
        assert seen[0].exec_type is FIXExecType.NEW

    def test_absent_quantities_read_as_zero(self, adapter, monkeypatch) -> None:
        seen = self._dispatched(adapter, monkeypatch)
        raw = f"8=FIX.4.4{SOH}35=8{SOH}11=CL-1{SOH}150=0{SOH}10=000{SOH}".encode()
        adapter._handle_pyfixmsg_message(raw)
        assert (seen[0].filled_qty, seen[0].avg_px, seen[0].cum_qty) == (0.0, 0.0, 0.0)

    def test_a_report_with_no_clordid_is_still_dispatched(self, adapter, monkeypatch) -> None:
        seen = self._dispatched(adapter, monkeypatch)
        adapter._handle_pyfixmsg_message(f"8=FIX.4.4{SOH}35=8{SOH}150=2{SOH}10=000{SOH}".encode())
        assert seen[0].cl_ord_id == "<unknown>"

    def test_a_logout_is_logged_with_its_reason(self, adapter, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="execution.fix_adapter"):
            adapter._handle_pyfixmsg_message(f"8=FIX.4.4{SOH}35=5{SOH}58=MsgSeqNum too low{SOH}10=000{SOH}".encode())
        assert "MsgSeqNum too low" in caplog.text

    def test_a_session_reject_is_logged_with_ref_seq_and_text(self, adapter, caplog) -> None:
        with caplog.at_level(logging.ERROR, logger="execution.fix_adapter"):
            adapter._handle_pyfixmsg_message(f"8=FIX.4.4{SOH}35=3{SOH}45=9{SOH}58=Invalid tag{SOH}10=000{SOH}".encode())
        assert "ref_seq=9" in caplog.text
        assert "Invalid tag" in caplog.text

    @pytest.mark.parametrize("msg_type", ["0", "1", "2", "4", "A", "W"])
    def test_every_other_message_type_dispatches_nothing(self, adapter, monkeypatch, msg_type: str) -> None:
        seen = self._dispatched(adapter, monkeypatch)
        adapter._handle_pyfixmsg_message(f"8=FIX.4.4{SOH}35={msg_type}{SOH}10=000{SOH}".encode())
        assert seen == []

    def test_an_unparseable_quantity_is_logged_not_raised(self, adapter, caplog) -> None:
        """This runs on the reader thread. An exception here kills the reader
        and the session goes silent while the adapter still looks connected."""
        with caplog.at_level(logging.ERROR, logger="execution.fix_adapter"):
            adapter._handle_pyfixmsg_message(_raw_exec_report(**{"32": "not-a-number"}))
        assert "parse error" in caplog.text

    def test_an_unknown_side_is_logged_not_raised(self, adapter, caplog) -> None:
        with caplog.at_level(logging.ERROR, logger="execution.fix_adapter"):
            adapter._handle_pyfixmsg_message(_raw_exec_report(**{"54": "7"}))
        assert "parse error" in caplog.text

    def test_undecodable_bytes_do_not_kill_the_reader(self, adapter) -> None:
        adapter._handle_pyfixmsg_message(b"\xff\xfe\x00 not fix at all")

    def test_an_empty_frame_is_ignored(self, adapter) -> None:
        adapter._handle_pyfixmsg_message(b"")


# ---------------------------------------------------------------------------
# send_order
# ---------------------------------------------------------------------------


class TestSendingAnOrderAndAwaitingTheFill:
    def test_an_open_circuit_refuses_the_order_before_it_is_built(self) -> None:
        """The breaker is checked first, so a degraded session sends nothing —
        not even a message it then fails to match to a fill."""
        adapter = FIXAdapter()
        adapter.circuit_breaker.record_latency(500.0)
        with pytest.raises(RuntimeError, match="circuit breaker is OPEN"):
            asyncio.run(adapter.send_order(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0)))
        assert adapter._pending == {}

    def test_simulation_resolves_with_a_synthetic_fill(self) -> None:
        adapter = FIXAdapter()
        report = asyncio.run(adapter.send_order(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=2.0)))
        assert report.exec_type is FIXExecType.FILL
        assert report.filled_qty == 2.0

    def test_the_synthetic_fill_is_indistinguishable_from_a_real_one(self) -> None:
        """A finding, pinned rather than fixed.

        With no FIX library installed `_FIX_BACKEND` is "none" and every order
        resolves against `_simulate_fill` — a full fill, at the order's own
        limit price or at a hard-coded 1950.0 for a market order. Nothing on
        the report marks it synthetic, and no caller checks the backend
        (`execution/fix_router.py` and `brokers/ibkr_fix_bridge.py` never read
        `_FIX_BACKEND`). A deployment whose quickfix build failed would book
        positions against a broker that never saw an order.

        Production installs quickfix (`requirements.txt:185`) and CI depends on
        this simulation, so the fix is to *mark* the report rather than to
        refuse it — a change to what a money-path report carries, which is the
        owner's call, not a coverage task's.
        """
        adapter = FIXAdapter()
        report = asyncio.run(adapter.send_order(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0)))
        assert report.text == ""
        assert report.avg_px == 1950.0

    def test_a_limit_order_simulates_at_its_own_price(self) -> None:
        adapter = FIXAdapter()
        order = FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, ord_type=FIXOrdType.LIMIT, price=1900.0)
        assert asyncio.run(adapter.send_order(order)).avg_px == 1900.0

    def test_the_simulated_fill_leaves_nothing_outstanding(self) -> None:
        adapter = FIXAdapter()
        report = asyncio.run(adapter.send_order(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=3.0)))
        assert report.leaves_qty == 0.0
        assert report.cum_qty == 3.0

    def test_the_pending_entry_is_cleared_once_resolved(self) -> None:
        """`_pending` is keyed by ClOrdID and never swept. An entry left behind
        is a leaked future for the life of the process."""
        adapter = FIXAdapter()
        asyncio.run(adapter.send_order(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0)))
        assert adapter._pending == {}

    def test_the_quickfix_backend_is_used_when_selected(self, monkeypatch) -> None:
        monkeypatch.setattr(fa, "_FIX_BACKEND", "quickfix")
        adapter = FIXAdapter()
        order = FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, cl_ord_id="CL-1")
        sent: list[FIXOrder] = []

        def _send(o: FIXOrder) -> None:
            sent.append(o)
            adapter._dispatch_exec_report(
                FIXFillReport("CL-1", "B-1", FIXExecType.FILL, "XAUUSD", FIXSide.BUY, 1.0, 1950.0, 0.0, 1.0)
            )

        monkeypatch.setattr(adapter, "_send_quickfix", _send)
        report = asyncio.run(adapter.send_order(order))
        assert sent == [order]
        assert report.order_id == "B-1"

    def test_the_pyfixmsg_backend_is_used_when_selected(self, monkeypatch) -> None:
        monkeypatch.setattr(fa, "_FIX_BACKEND", "pyfixmsg")
        adapter = FIXAdapter()
        sent: list[FIXOrder] = []

        def _send(o: FIXOrder) -> None:
            sent.append(o)
            adapter._dispatch_exec_report(
                FIXFillReport(o.cl_ord_id, "B-2", FIXExecType.FILL, "XAUUSD", FIXSide.SELL, 1.0, 1950.0, 0.0, 1.0)
            )

        monkeypatch.setattr(adapter, "_send_pyfixmsg", _send)
        report = asyncio.run(adapter.send_order(FIXOrder(symbol="XAUUSD", side=FIXSide.SELL, quantity=1.0)))
        assert len(sent) == 1
        assert report.order_id == "B-2"

    def test_a_rejection_reaches_the_caller_as_an_exception(self, monkeypatch) -> None:
        monkeypatch.setattr(fa, "_FIX_BACKEND", "quickfix")
        adapter = FIXAdapter()

        def _send(o: FIXOrder) -> None:
            adapter._dispatch_exec_report(
                FIXFillReport(
                    o.cl_ord_id,
                    "",
                    FIXExecType.REJECTED,
                    "",
                    FIXSide.BUY,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    text="Account not authorised",
                )
            )

        monkeypatch.setattr(adapter, "_send_quickfix", _send)
        with pytest.raises(RuntimeError, match="Account not authorised"):
            asyncio.run(adapter.send_order(FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0)))

    def test_a_fill_that_never_arrives_times_out_and_frees_the_slot(self, monkeypatch) -> None:
        """The 30-second timeout is not exercised at its real length here; what
        matters is that the pending entry is removed when it fires, so a
        retried ClOrdID is not answered by the abandoned future."""
        monkeypatch.setattr(fa, "_FIX_BACKEND", "quickfix")
        adapter = FIXAdapter()
        monkeypatch.setattr(adapter, "_send_quickfix", lambda o: None)

        async def _immediate_timeout(awaitable: Any, timeout: float) -> Any:
            awaitable.cancel()
            raise TimeoutError

        monkeypatch.setattr(fa.asyncio, "wait_for", _immediate_timeout)
        order = FIXOrder(symbol="XAUUSD", side=FIXSide.BUY, quantity=1.0, cl_ord_id="CL-STUCK")
        with pytest.raises(TimeoutError, match="CL-STUCK"):
            asyncio.run(adapter.send_order(order))
        assert adapter._pending == {}


class TestResolvingTheCallersFuture:
    def _adapter_with_pending(self, cl_ord_id: str, loop: asyncio.AbstractEventLoop):
        adapter = FIXAdapter()
        future: asyncio.Future[FIXFillReport] = loop.create_future()
        adapter._pending[cl_ord_id] = future
        return adapter, future

    def test_a_fill_resolves_the_matching_future(self) -> None:
        async def _run() -> FIXFillReport:
            loop = asyncio.get_running_loop()
            adapter, future = self._adapter_with_pending("CL-1", loop)
            adapter._dispatch_exec_report(
                FIXFillReport("CL-1", "B-1", FIXExecType.FILL, "XAUUSD", FIXSide.BUY, 1.0, 1950.0, 0.0, 1.0)
            )
            return await future

        assert asyncio.run(_run()).order_id == "B-1"

    def test_a_rejection_resolves_it_as_an_exception(self) -> None:
        async def _run() -> None:
            loop = asyncio.get_running_loop()
            adapter, future = self._adapter_with_pending("CL-1", loop)
            adapter._dispatch_exec_report(
                FIXFillReport("CL-1", "", FIXExecType.REJECTED, "", FIXSide.BUY, 0.0, 0.0, 0.0, 0.0, text="no")
            )
            with pytest.raises(RuntimeError, match="rejected by broker"):
                await future

        asyncio.run(_run())

    def test_the_future_is_removed_when_it_is_resolved(self) -> None:
        async def _run() -> None:
            loop = asyncio.get_running_loop()
            adapter, future = self._adapter_with_pending("CL-1", loop)
            adapter._dispatch_exec_report(
                FIXFillReport("CL-1", "B-1", FIXExecType.FILL, "XAUUSD", FIXSide.BUY, 1.0, 1950.0, 0.0, 1.0)
            )
            await future
            assert adapter._pending == {}

        asyncio.run(_run())

    def test_only_the_matching_order_is_resolved(self) -> None:
        """Two orders in flight is the ordinary case. Resolving the wrong future
        pairs a fill with the other order's size."""

        async def _run() -> None:
            loop = asyncio.get_running_loop()
            adapter, first = self._adapter_with_pending("CL-1", loop)
            second: asyncio.Future[FIXFillReport] = loop.create_future()
            adapter._pending["CL-2"] = second
            adapter._dispatch_exec_report(
                FIXFillReport("CL-2", "B-2", FIXExecType.FILL, "XAUUSD", FIXSide.BUY, 1.0, 1950.0, 0.0, 1.0)
            )
            assert (await second).order_id == "B-2"
            assert not first.done()
            first.cancel()

        asyncio.run(_run())

    def test_an_unsolicited_report_is_dropped_quietly(self, caplog) -> None:
        adapter = FIXAdapter()
        with caplog.at_level(logging.DEBUG, logger="execution.fix_adapter"):
            adapter._dispatch_exec_report(
                FIXFillReport("CL-UNKNOWN", "B-1", FIXExecType.FILL, "XAUUSD", FIXSide.BUY, 1.0, 1950.0, 0.0, 1.0)
            )
        assert "unsolicited exec report" in caplog.text

    def test_a_second_report_for_the_same_order_finds_nothing_to_resolve(self) -> None:
        """A partial fill followed by a fill is two reports for one ClOrdID.
        The second must not raise InvalidStateError on the reader thread."""

        async def _run() -> None:
            loop = asyncio.get_running_loop()
            adapter, future = self._adapter_with_pending("CL-1", loop)
            report = FIXFillReport("CL-1", "B-1", FIXExecType.FILL, "XAUUSD", FIXSide.BUY, 1.0, 1950.0, 0.0, 1.0)
            adapter._dispatch_exec_report(report)
            adapter._dispatch_exec_report(report)
            await future

        asyncio.run(_run())

    def test_an_already_cancelled_future_is_left_alone(self) -> None:
        async def _run() -> None:
            loop = asyncio.get_running_loop()
            adapter, future = self._adapter_with_pending("CL-1", loop)
            future.cancel()
            adapter._dispatch_exec_report(
                FIXFillReport("CL-1", "B-1", FIXExecType.FILL, "XAUUSD", FIXSide.BUY, 1.0, 1950.0, 0.0, 1.0)
            )

        asyncio.run(_run())

    def test_a_dead_event_loop_is_warned_about_not_raised(self, caplog) -> None:
        """The dispatcher runs on the FIX reader thread. If the loop is gone,
        the reader must survive it."""
        loop = asyncio.new_event_loop()
        adapter = FIXAdapter()
        future: asyncio.Future[FIXFillReport] = loop.create_future()
        adapter._pending["CL-1"] = future
        loop.close()
        with caplog.at_level(logging.WARNING, logger="execution.fix_adapter"):
            adapter._dispatch_exec_report(
                FIXFillReport("CL-1", "B-1", FIXExecType.FILL, "XAUUSD", FIXSide.BUY, 1.0, 1950.0, 0.0, 1.0)
            )
        assert "_dispatch_exec_report" in caplog.text


# ---------------------------------------------------------------------------
# SmartOrderRouter hook
# ---------------------------------------------------------------------------


class TestTheRouterHook:
    """The boundary `brokers/smart_router.py` sees: a dict in, a dict out."""

    @pytest.fixture
    def route(self):
        return FIXAdapter().route_hook()

    def test_a_buy_becomes_a_fix_buy(self) -> None:
        adapter = FIXAdapter()
        captured: list[FIXOrder] = []

        async def _capture(order: FIXOrder) -> FIXFillReport:
            captured.append(order)
            return adapter._simulate_fill(order)

        adapter.send_order = _capture  # type: ignore[method-assign]
        asyncio.run(adapter.route_hook()({"symbol": "XAUUSD", "side": "BUY", "quantity": 2.0}))
        assert captured[0].side is FIXSide.BUY
        assert captured[0].symbol == "XAUUSD"
        assert captured[0].quantity == 2.0

    @pytest.mark.parametrize("side", ["SELL", "sell", "Sell", "S", "", "anything else"])
    def test_anything_that_is_not_exactly_buy_is_a_sell(self, side: str) -> None:
        """Pinned because it is surprising: the comparison is an exact match on
        "BUY", so a lower-case "buy" routes a SELL. Every caller in this repo
        passes upper case; a new one must not discover this by filling."""
        adapter = FIXAdapter()
        captured: list[FIXOrder] = []

        async def _capture(order: FIXOrder) -> FIXFillReport:
            captured.append(order)
            return adapter._simulate_fill(order)

        adapter.send_order = _capture  # type: ignore[method-assign]
        asyncio.run(adapter.route_hook()({"symbol": "XAUUSD", "side": side, "quantity": 1.0}))
        assert captured[0].side is FIXSide.SELL

    def test_a_missing_side_defaults_to_buy(self) -> None:
        adapter = FIXAdapter()
        captured: list[FIXOrder] = []

        async def _capture(order: FIXOrder) -> FIXFillReport:
            captured.append(order)
            return adapter._simulate_fill(order)

        adapter.send_order = _capture  # type: ignore[method-assign]
        asyncio.run(adapter.route_hook()({"symbol": "XAUUSD", "quantity": 1.0}))
        assert captured[0].side is FIXSide.BUY

    def test_it_always_routes_a_market_order(self, route) -> None:
        """The router hook has no price argument that reaches OrdType. Anything
        else would be a limit with no price."""
        adapter = FIXAdapter()
        captured: list[FIXOrder] = []

        async def _capture(order: FIXOrder) -> FIXFillReport:
            captured.append(order)
            return adapter._simulate_fill(order)

        adapter.send_order = _capture  # type: ignore[method-assign]
        asyncio.run(adapter.route_hook()({"symbol": "XAUUSD", "side": "BUY", "quantity": 1.0, "price": 1950.0}))
        assert captured[0].ord_type is FIXOrdType.MARKET

    def test_a_missing_quantity_defaults_to_one(self, route) -> None:
        assert asyncio.run(route({"symbol": "XAUUSD", "side": "BUY"}))["filled_qty"] == 1.0

    def test_a_string_quantity_is_coerced(self, route) -> None:
        assert asyncio.run(route({"symbol": "XAUUSD", "side": "BUY", "quantity": "2.5"}))["filled_qty"] == 2.5

    def test_a_missing_symbol_is_refused_rather_than_guessed(self, route) -> None:
        """Defaulting the instrument would route an order for something nobody
        asked for."""
        with pytest.raises(KeyError):
            asyncio.run(route({"side": "BUY", "quantity": 1.0}))

    def test_the_result_names_this_broker_and_the_ids(self, route) -> None:
        result = asyncio.run(route({"symbol": "XAUUSD", "side": "BUY", "quantity": 1.0}))
        assert result["broker"] == "fix"
        assert set(result) == {"broker", "cl_ord_id", "order_id", "filled_qty", "avg_px", "latency_ms", "exec_type"}

    def test_the_exec_type_is_reported_by_name_not_wire_code(self, route) -> None:
        assert asyncio.run(route({"symbol": "XAUUSD", "side": "BUY", "quantity": 1.0}))["exec_type"] == "FILL"

    def test_each_call_returns_a_fresh_coroutine_function(self) -> None:
        adapter = FIXAdapter()
        assert adapter.route_hook() is not adapter.route_hook()
        assert asyncio.iscoroutinefunction(adapter.route_hook())


class TestAMalformedReportReachesTheCallerNotTheTimeout:
    """End to end, through the dispatcher rather than the callback.

    This is the failure the handlers' `except` clauses exist to prevent, so it
    is worth asserting at the boundary the caller actually sees: a future that
    raises, rather than one that hangs until `send_order` gives up at 30
    seconds. Two separate defects had to be fixed for it to hold — the
    exception type nobody caught, and a rejection filed under `<unknown>`
    because ClOrdID was read as part of the same bulk extraction that failed.
    """

    def test_a_report_missing_a_required_field_fails_the_caller_immediately(self, fake_fix) -> None:
        async def _run() -> None:
            loop = asyncio.get_running_loop()
            adapter = FIXAdapter()
            adapter._app = _QuickfixApp(
                on_exec_report=adapter._dispatch_exec_report, circuit_breaker=adapter.circuit_breaker
            )
            future: asyncio.Future[FIXFillReport] = loop.create_future()
            adapter._pending["CL-1"] = future

            adapter._app._handle_exec_report(_exec_report_message(drop=[6]))

            with pytest.raises(RuntimeError, match="rejected by broker"):
                await asyncio.wait_for(future, timeout=5.0)

        asyncio.run(_run())

    def test_a_cancel_reject_missing_its_text_fails_the_caller_immediately(self, fake_fix) -> None:
        async def _run() -> None:
            loop = asyncio.get_running_loop()
            adapter = FIXAdapter()
            adapter._app = _QuickfixApp(
                on_exec_report=adapter._dispatch_exec_report, circuit_breaker=adapter.circuit_breaker
            )
            future: asyncio.Future[FIXFillReport] = loop.create_future()
            adapter._pending["CL-1"] = future

            adapter._app._handle_order_cancel_reject(_FakeMessage({11: "CL-1", 102: "1"}))

            with pytest.raises(RuntimeError, match="rejected by broker"):
                await asyncio.wait_for(future, timeout=5.0)

        asyncio.run(_run())

    def test_a_well_formed_report_still_resolves_normally(self, fake_fix) -> None:
        """The widened handlers must not turn a good fill into a rejection."""

        async def _run() -> FIXFillReport:
            loop = asyncio.get_running_loop()
            adapter = FIXAdapter()
            adapter._app = _QuickfixApp(
                on_exec_report=adapter._dispatch_exec_report, circuit_breaker=adapter.circuit_breaker
            )
            future: asyncio.Future[FIXFillReport] = loop.create_future()
            adapter._pending["CL-1"] = future
            adapter._app._handle_exec_report(_exec_report_message())
            return await asyncio.wait_for(future, timeout=5.0)

        report = asyncio.run(_run())
        assert report.exec_type is FIXExecType.FILL
        assert report.avg_px == 1950.25


class TestStartPicksTheBackendItWasBuiltFor:
    """`start()` is the only place the backend choice is acted on. Sending a
    quickfix deployment down the pyfixmsg branch would open a raw socket
    alongside the managed session — two logons, one of them unsequenced."""

    @pytest.fixture(autouse=True)
    def _development(self, clean_env, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APP_ENV", "development")

    def _adapter(self) -> FIXAdapter:
        adapter = FIXAdapter()
        adapter.HEARTBEAT_INTERVAL = 0.01  # type: ignore[misc]
        return adapter

    def test_the_quickfix_backend_brings_up_a_quickfix_session(self, monkeypatch) -> None:
        monkeypatch.setattr(fa, "_FIX_BACKEND", "quickfix")
        adapter = self._adapter()
        called: list[str] = []
        monkeypatch.setattr(adapter, "_start_quickfix", lambda: called.append("quickfix"))
        monkeypatch.setattr(adapter, "_start_pyfixmsg", lambda: called.append("pyfixmsg"))
        try:
            adapter.start()
        finally:
            adapter.stop()
        assert called == ["quickfix"]

    def test_the_pyfixmsg_backend_brings_up_a_socket_session(self, monkeypatch) -> None:
        monkeypatch.setattr(fa, "_FIX_BACKEND", "pyfixmsg")
        adapter = self._adapter()
        called: list[str] = []
        monkeypatch.setattr(adapter, "_start_quickfix", lambda: called.append("quickfix"))
        monkeypatch.setattr(adapter, "_start_pyfixmsg", lambda: called.append("pyfixmsg"))
        try:
            adapter.start()
        finally:
            adapter.stop()
        assert called == ["pyfixmsg"]

    def test_neither_is_brought_up_without_a_library(self, monkeypatch) -> None:
        adapter = self._adapter()
        called: list[str] = []
        monkeypatch.setattr(adapter, "_start_quickfix", lambda: called.append("quickfix"))
        monkeypatch.setattr(adapter, "_start_pyfixmsg", lambda: called.append("pyfixmsg"))
        try:
            adapter.start()
        finally:
            adapter.stop()
        assert called == []

    def test_the_heartbeat_runs_whichever_backend_was_chosen(self, monkeypatch) -> None:
        """It reports the circuit breaker, which guards every backend."""
        monkeypatch.setattr(fa, "_FIX_BACKEND", "quickfix")
        adapter = self._adapter()
        monkeypatch.setattr(adapter, "_start_quickfix", lambda: None)
        try:
            adapter.start()
            assert adapter._hb_thread is not None and adapter._hb_thread.is_alive()
        finally:
            adapter.stop()
