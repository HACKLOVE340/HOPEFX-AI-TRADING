# Phase E — Risk Gates Implementation Plan

> **For agentic workers:** implement task-by-task. Steps use checkbox (`- [ ]`)
> syntax for tracking. Each task ends with an independently testable deliverable
> and a commit.

**Goal:** Put a real risk layer in front of the order path that is running
today, and stop two constants — an unrouted regime and a fixed order size —
from deciding how much money each trade risks.

**Architecture:** The active paper path is `PaperRunner → bus(CH_ORDER) →
FIXRouter._route → broker`. `FIXRouter._route` currently has one gate
(`if self._halted`). Rather than duplicating risk logic there, the router gains
an injected gate object with a single method; production injects the real
`RiskManager`, tests inject a stub. That keeps `fix_router.py` free of risk
policy and makes the gate independently testable.

**Tech Stack:** Python 3.12, asyncio, pytest, existing `risk/manager.py`,
`invariants/enforcement.py`.

**Findings this implements:** F142 (CRITICAL), F94 (HIGH), F61/F107 (CRITICAL),
F84. Full text in `docs/audit/CODE_READING_FINDINGS.md`.

## Global Constraints

- **Never weaken a risk gate, kill switch, or staleness/drift check** (CLAUDE.md).
  Every task here only adds refusals; none removes one.
- Money values that become an order quantity are `Decimal` by the time they are
  authoritative (`hopefx-money-precision` skill). `risk/manager.py` is on the
  float side of that line today; do not move it further toward float.
- Invariant predicates stay pure. Only `invariants/enforcement.py` decides what
  a violation does (`hopefx-invariants` skill).
- `ruff check .` clean and all 15 pre-commit hooks pass before every commit.
  Never `--no-verify`.
- Verify the full suite in a **fresh worktree with `static/` copied in** (F244),
  and diff the failure set against the baseline rather than reading the count.
- Branch: `claude/add-new-skills-lys862`. No PR unless asked.

---

### Task 1: A pre-trade gate the paper router can call

The router must not import risk policy. It gets an object with one method.

**Files:**
- Create: `execution/order_gate.py`
- Test: `tests/unit/test_order_gate.py`

**Interfaces:**
- Produces: `OrderGate` protocol with
  `async def check(self, order_request: dict) -> GateDecision`
- Produces: `GateDecision(allowed: bool, reason: str, quantity: float | None)`
- Produces: `RiskManagerGate(risk_manager)` implementing `OrderGate`
- Produces: `AlwaysAllowGate()` — explicit, named, and **logs a warning on every
  call**, so an unconfigured deployment is loud rather than silent

- [ ] **Step 1: Write the failing test**

```python
import pytest
from execution.order_gate import AlwaysAllowGate, GateDecision, RiskManagerGate

pytestmark = pytest.mark.unit


class _Assessment:
    def __init__(self, approved, reason="", quantity=None):
        self.approved = approved
        self.reason = reason
        self.sizing = type("S", (), {"quantity": quantity})() if quantity else None


@pytest.mark.asyncio
async def test_a_rejected_assessment_blocks_the_order():
    class RM:
        def assess(self, signal):
            return _Assessment(False, reason="daily_dd:6.10%")

    decision = await RiskManagerGate(RM()).check(
        {"symbol": "XAUUSD", "direction": "BUY", "units": 1000.0}
    )
    assert decision.allowed is False
    assert "daily_dd" in decision.reason


@pytest.mark.asyncio
async def test_an_approved_assessment_returns_the_risk_managers_size():
    class RM:
        def assess(self, signal):
            return _Assessment(True, reason="ok", quantity=37.5)

    decision = await RiskManagerGate(RM()).check(
        {"symbol": "XAUUSD", "direction": "BUY", "units": 1000.0}
    )
    assert decision.allowed is True
    assert decision.quantity == 37.5, "the fixed PAPER_ORDER_UNITS constant survived the gate"


@pytest.mark.asyncio
async def test_a_raising_risk_manager_fails_closed():
    class RM:
        def assess(self, signal):
            raise RuntimeError("feature store down")

    decision = await RiskManagerGate(RM()).check({"symbol": "XAUUSD", "direction": "BUY"})
    assert decision.allowed is False, "a broken risk manager let an unsized order through"


@pytest.mark.asyncio
async def test_the_always_allow_gate_says_so_loudly(caplog):
    with caplog.at_level("WARNING"):
        decision = await AlwaysAllowGate().check({"symbol": "XAUUSD"})
    assert decision.allowed is True
    assert any("no risk gate" in r.message.lower() for r in caplog.records), (
        "an unconfigured deployment trades with no risk layer and says nothing"
    )
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `pytest tests/unit/test_order_gate.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'execution.order_gate'`

- [ ] **Step 3: Implement `execution/order_gate.py`**

```python
"""The pre-trade gate the order routers call.

FIXRouter had exactly one gate — ``if self._halted`` — and then went straight to
the broker (F142). Risk policy does not belong in a router, so the router takes
an object with one method instead: production injects the real RiskManager,
tests inject a stub, and neither has to know about the other.

Fails closed. A gate that cannot reach its risk manager refuses the order: an
unsized trade is not a smaller problem than a blocked one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str
    #: Size the gate authorises, in units. None means "use the caller's".
    quantity: float | None = None


class OrderGate(Protocol):
    async def check(self, order_request: dict[str, Any]) -> GateDecision: ...


class RiskManagerGate:
    """Routes an order_request through RiskManager.assess()."""

    def __init__(self, risk_manager: Any) -> None:
        self._rm = risk_manager

    async def check(self, order_request: dict[str, Any]) -> GateDecision:
        try:
            assessment = self._rm.assess(order_request)
        except Exception:
            logger.exception("Pre-trade risk assessment failed — REFUSING order (fail closed)")
            return GateDecision(False, "risk_assessment_error")

        if not getattr(assessment, "approved", False):
            reason = getattr(assessment, "reason", "rejected")
            logger.warning("Pre-trade gate REFUSED %s: %s", order_request.get("symbol"), reason)
            return GateDecision(False, reason)

        sizing = getattr(assessment, "sizing", None)
        quantity = getattr(sizing, "quantity", None) if sizing is not None else None
        return GateDecision(True, getattr(assessment, "reason", "ok"), quantity)


class AlwaysAllowGate:
    """No risk layer. Explicit and loud, never a silent default."""

    async def check(self, order_request: dict[str, Any]) -> GateDecision:
        logger.warning(
            "ORDER PLACED WITH NO RISK GATE: symbol=%s. No sizing, drawdown or "
            "exposure check was applied. Wire a RiskManager.",
            order_request.get("symbol"),
        )
        return GateDecision(True, "no_gate_configured")
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/unit/test_order_gate.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
ruff check . && pre-commit run --all-files
git add execution/order_gate.py tests/unit/test_order_gate.py
git commit -m "feat(execution): a pre-trade gate the order routers can call (F142, part 1)"
```

---

### Task 2: Wire the gate into the path that is actually running

**Files:**
- Modify: `execution/fix_router.py` (`__init__`, `_route`)
- Test: `tests/unit/test_fix_router_has_a_risk_gate.py`

**Interfaces:**
- Consumes: `OrderGate`, `GateDecision`, `AlwaysAllowGate` from Task 1
- Produces: `FIXRouter(..., gate: OrderGate | None = None)`; when `gate is None`
  it uses `AlwaysAllowGate()`, which logs on every order

- [ ] **Step 1: Write the failing test**

```python
import pytest
from execution.order_gate import GateDecision

pytestmark = pytest.mark.unit


class _Gate:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    async def check(self, order_request):
        self.calls.append(order_request)
        return self.decision


@pytest.mark.asyncio
async def test_a_refused_order_never_reaches_the_broker(monkeypatch):
    from execution.fix_router import FIXRouter

    gate = _Gate(GateDecision(False, "daily_dd:6.10%"))
    router = FIXRouter(gate=gate)
    sent = []
    monkeypatch.setattr(router, "_send_paper", lambda *a, **k: sent.append(a))

    await router._route({"symbol": "XAUUSD", "direction": "BUY", "units": 1000.0})

    assert gate.calls, "the router did not consult the gate at all"
    assert sent == [], "a risk-refused order was sent to the broker"


@pytest.mark.asyncio
async def test_the_gates_size_replaces_the_fixed_constant(monkeypatch):
    from execution.fix_router import FIXRouter

    router = FIXRouter(gate=_Gate(GateDecision(True, "ok", quantity=37.5)))
    seen = {}

    async def _capture(symbol, direction, units, req):
        seen["units"] = units
        return {"status": "filled"}

    monkeypatch.setattr(router, "_send_paper", _capture)
    monkeypatch.setattr(router, "_on_fill", lambda fill: None)
    router._paper_broker = object()

    await router._route({"symbol": "XAUUSD", "direction": "BUY", "units": 1000.0})

    assert seen["units"] == 37.5, "PAPER_ORDER_UNITS was used instead of the risk-manager size"


@pytest.mark.asyncio
async def test_the_halt_gate_still_wins():
    """Regression guard: adding a gate must not displace the kill switch."""
    from execution.fix_router import FIXRouter

    gate = _Gate(GateDecision(True, "ok"))
    router = FIXRouter(gate=gate)
    router._halted = True

    await router._route({"symbol": "XAUUSD", "direction": "BUY", "units": 1.0})

    assert gate.calls == [], "the router consulted the gate while halted"
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `pytest tests/unit/test_fix_router_has_a_risk_gate.py -q`
Expected: FAIL — `FIXRouter.__init__() got an unexpected keyword argument 'gate'`

- [ ] **Step 3: Add the parameter and the call**

`FIXRouter.__init__` is `def __init__(self) -> None:` at `execution/fix_router.py:172`
— it takes no arguments today. Change it to
`def __init__(self, gate: "OrderGate | None" = None) -> None:` and add, after the
existing assignments:

```python
        # Pre-trade gate. None means no risk layer, which AlwaysAllowGate
        # announces on every order rather than passing silently (F142).
        from execution.order_gate import AlwaysAllowGate, OrderGate  # noqa: PLC0415

        self._gate: OrderGate = gate if gate is not None else AlwaysAllowGate()
```

In `_route`, immediately after the `self._halted` block and before `symbol = ...`:

```python
        # The kill switch above is a halt, not a risk assessment. Everything
        # below it used to run with no gate of any kind: no sizing, no drawdown
        # check, no exposure limit, and a fixed PAPER_ORDER_UNITS size (F142).
        decision = await self._gate.check(order_request)
        if not decision.allowed:
            self._rejected_count += 1
            logger.warning(
                "FIXRouter: order REFUSED by pre-trade gate — %s (%s)",
                order_request.get("symbol"),
                decision.reason,
            )
            return
        if decision.quantity is not None:
            order_request = {**order_request, "units": decision.quantity}
```

Add `self._rejected_count = 0` beside `self._order_count` in `__init__`.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/unit/test_fix_router_has_a_risk_gate.py tests/unit/test_order_gate.py -q`
Expected: 7 passed

- [ ] **Step 5: Run every existing fix_router test**

Run: `pytest -q -k "fix_router or paper_runner" -m "not slow and not e2e"`
Expected: no new failures against the baseline

- [ ] **Step 6: Commit**

```bash
ruff check . && pre-commit run --all-files
git add execution/fix_router.py tests/unit/test_fix_router_has_a_risk_gate.py
git commit -m "fix(execution): the paper order path now has a pre-trade risk gate (F142)"
```

---

### Task 3: Inject the real RiskManager in production startup

A gate nothing injects is the same defect in a new place.

**Files:**
- Modify: `execution/paper_runner.py` (where `FIXRouter` is constructed)
- Test: `tests/unit/test_paper_runner_wires_the_gate.py`

**Interfaces:**
- Consumes: `RiskManagerGate` from Task 1, `FIXRouter(gate=...)` from Task 2

- [ ] **Step 1: Confirm the construction site**

`execution/paper_runner.py:667` — `self._router = FIXRouter()`.
Run `grep -n "FIXRouter(" execution/paper_runner.py` to confirm the line has not moved.

- [ ] **Step 2: Write the failing test**

```python
import pytest

pytestmark = pytest.mark.unit


def test_the_paper_runner_gives_its_router_a_real_gate():
    """A gate nothing injects is F142 in a new location."""
    from execution.order_gate import AlwaysAllowGate
    from execution.paper_runner import PaperRunner

    runner = PaperRunner()
    router = runner._build_router()

    assert not isinstance(router._gate, AlwaysAllowGate), (
        "the paper runner wired no risk gate; orders route unsized"
    )
```

- [ ] **Step 3: Run it and confirm it fails**

Run: `pytest tests/unit/test_paper_runner_wires_the_gate.py -q`
Expected: FAIL — either `_build_router` missing, or the gate is `AlwaysAllowGate`

- [ ] **Step 4: Extract `_build_router()` and inject the gate**

```python
    def _build_router(self):
        """Construct the order router with its pre-trade gate.

        Extracted so the wiring is testable: the gate existing is worth nothing
        if the runner never passes one (F142).
        """
        from execution.fix_router import FIXRouter
        from execution.order_gate import RiskManagerGate
        from risk.manager import RiskManager

        return FIXRouter(gate=RiskManagerGate(RiskManager()))
```

Replace `self._router = FIXRouter()` at line 667 with `self._router = self._build_router()`.

- [ ] **Step 5: Run the tests**

Run: `pytest tests/unit/test_paper_runner_wires_the_gate.py -q`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
ruff check . && pre-commit run --all-files
git add execution/paper_runner.py tests/unit/test_paper_runner_wires_the_gate.py
git commit -m "fix(execution): paper runner injects a real risk gate (F142)"
```

---

### Task 4: Stop the unrouted regime halving every position

**Files:**
- Modify: `core/signal_engine.py:175-181` (`_REGIME_SIZE_MAP.get(name.upper(), 0.5)`)
- Test: `tests/unit/test_regime_scalar_is_not_a_silent_default.py`

**Interfaces:**
- Produces: `get_regime_position_scalar(name)` raising or returning 1.0 with a
  loud log for an unknown regime — never a silent 0.5

- [ ] **Step 1: Write the failing test**

```python
import pytest

pytestmark = pytest.mark.unit


def test_an_unknown_regime_does_not_silently_halve_the_position(caplog):
    """RegimeRouter.route() is never called, so the regime is the constructor's
    "unknown" for ever, and .get(name, 0.5) halves every position on the
    platform (F94). Proven by execution in the findings log."""
    from core.signal_engine import get_regime_position_scalar

    with caplog.at_level("WARNING"):
        scalar = get_regime_position_scalar("unknown")

    assert scalar != 0.5, "an undetected regime still halves the position"
    assert any("regime" in r.message.lower() for r in caplog.records), (
        "the position was scaled by a default nobody was told about"
    )


@pytest.mark.parametrize("regime", ["TRENDING", "RANGING", "VOLATILE"])
def test_a_known_regime_keeps_its_configured_scalar(regime):
    from core.signal_engine import _REGIME_SIZE_MAP, get_regime_position_scalar

    assert get_regime_position_scalar(regime) == _REGIME_SIZE_MAP[regime]
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `pytest tests/unit/test_regime_scalar_is_not_a_silent_default.py -q`
Expected: FAIL — `assert 0.5 != 0.5`

- [ ] **Step 3: Make the default explicit and loud**

```python
def get_regime_position_scalar(regime_name: str) -> float:
    """Position-size multiplier for a market regime.

    The default was 0.5. Because RegimeRouter.route() is never called, the
    regime is always the constructor's "unknown", so that default was not an
    edge case — it halved **every** position the platform ever sized (F94).

    An undetected regime is missing information, not a reason to take half a
    position silently. Returning 1.0 leaves sizing to the risk manager, which is
    the component that owns it, and the warning makes the gap visible.
    """
    scalar = _REGIME_SIZE_MAP.get(regime_name.upper())
    if scalar is None:
        logger.warning(
            "Regime %r is not in the size map — sizing left to the risk manager. "
            "If this is constant, RegimeRouter.route() is not being called (F94).",
            regime_name,
        )
        return 1.0
    return scalar
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/unit/test_regime_scalar_is_not_a_silent_default.py -q`
Expected: 4 passed

- [ ] **Step 5: Run everything that touches sizing**

Run: `pytest -q -k "regime or sizing or signal_engine" -m "not slow and not e2e"`
Expected: no new failures. **Some tests may encode the 0.5 behaviour** — read
each before changing it and decide whether it pins the requirement or the bug.

- [ ] **Step 6: Commit**

```bash
ruff check . && pre-commit run --all-files
git add core/signal_engine.py tests/unit/test_regime_scalar_is_not_a_silent_default.py
git commit -m "fix(risk): an undetected regime no longer halves every position (F94)"
```

---

### Task 5: Make `BROKER_TYPE=oanda` fail at startup, not at the first order

`AsyncOANDAConnector = OANDABroker` is a bare alias with no
`place_market_order`. `trade_executor.py:409` calls it, so the first live order
raises `AttributeError`. `k8s-configmap.yaml:33-34` already sets
`BROKER_TYPE=oanda` with `OANDA_PRACTICE=false`.

Making OANDA work is a feature. Making it **stop pretending to work** is this
task: a deployment that cannot trade must refuse to start rather than discover
it on the first signal.

**Files:**
- Modify: `core/startup_factories.py:1154` (the `BROKER_TYPE=oanda` branch)
- Test: `tests/unit/test_broker_type_oanda_is_not_silently_broken.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

pytestmark = pytest.mark.unit

REQUIRED = ("place_market_order", "get_account_info", "get_positions")


def test_the_oanda_connector_satisfies_the_interface_trade_executor_calls():
    """execution/trade_executor.py:409 calls place_market_order. The class wired
    for BROKER_TYPE=oanda does not have it, so the first live order raises
    AttributeError before an order is constructed (F61/F107)."""
    from brokers.oanda import AsyncOANDAConnector

    missing = [m for m in REQUIRED if not hasattr(AsyncOANDAConnector, m)]
    assert not missing, (
        f"AsyncOANDAConnector is missing {missing}; BROKER_TYPE=oanda cannot place an order"
    )
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `pytest tests/unit/test_broker_type_oanda_is_not_silently_broken.py -q`
Expected: FAIL listing `['place_market_order', ...]`

- [ ] **Step 3: Refuse the configuration at startup**

In the `BROKER_TYPE=oanda` branch of `core/startup_factories.py`:

```python
        # Verify the connector can actually place an order before reporting the
        # broker as ready. AsyncOANDAConnector is a bare alias for OANDABroker,
        # which has no place_market_order — the method trade_executor.py:409
        # calls — so this configuration used to boot cleanly and fail on the
        # first signal instead (F61/F107). k8s-configmap.yaml already sets
        # BROKER_TYPE=oanda with OANDA_PRACTICE=false.
        _required = ("place_market_order", "get_account_info", "get_positions")
        _missing = [m for m in _required if not hasattr(broker, m)]
        if _missing:
            raise RuntimeError(
                f"BROKER_TYPE=oanda selected, but {type(broker).__name__} is missing "
                f"{_missing}. This deployment cannot place an order. Refusing to "
                "start rather than failing on the first signal."
            )
```

- [ ] **Step 4: Add the startup-refusal test**

```python
@pytest.mark.asyncio
async def test_startup_refuses_rather_than_booting_a_broker_that_cannot_trade(monkeypatch):
    monkeypatch.setenv("BROKER_TYPE", "oanda")
    from core import startup_factories

    # init_broker(s) takes the app-state object; a bare namespace is enough
    # to reach the BROKER_TYPE branch.
    class _S:
        broker = None

    with pytest.raises(RuntimeError, match="cannot place an order"):
        await startup_factories.init_broker(_S())
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/unit/test_broker_type_oanda_is_not_silently_broken.py -q`
Expected: the interface test still fails (that is the open feature); the startup
test passes. **Mark the interface test `xfail(strict=True)` with a reason
naming F61/F107**, so it flips to a failure the moment OANDA is implemented and
nobody has to remember to un-skip it.

- [ ] **Step 6: Commit**

```bash
ruff check . && pre-commit run --all-files
git add core/startup_factories.py tests/unit/test_broker_type_oanda_is_not_silently_broken.py
git commit -m "fix(brokers): BROKER_TYPE=oanda refuses to start instead of failing on the first order (F61/F107)"
```

---

### Task 6: Verify the phase against a clean baseline

- [ ] **Step 1: Fresh worktree with the build artifact**

```bash
SP=<scratchpad>
git worktree add $SP/phase-e-wt HEAD -q
cp -r static $SP/phase-e-wt/static      # gitignored; a worktree has none (F244)
```

- [ ] **Step 2: Copy the changed files in and run the fast suite**

```bash
cd $SP/phase-e-wt && python -m pytest -m "not slow and not e2e" -q -p no:cacheprovider
```

Expected: **17171 passed, 0 failed** plus the new tests. Diff the failure set
against the baseline; do not read the count alone.

- [ ] **Step 3: Update the findings log**

Mark F142, F94, F61/F107 with what was fixed and what was left open (OANDA
itself remains unimplemented — say so plainly rather than implying it works).

- [ ] **Step 4: Commit and push**

```bash
git add docs/audit/CODE_READING_FINDINGS.md docs/audit/FIX_PHASES.md
git commit -m "docs(audit): phase E complete — the paper path has a risk layer"
git push -u origin claude/add-new-skills-lys862
```

---

## Open questions for the owner

1. **F142 sizing source.** The gate uses `RiskManager.assess().sizing.quantity`.
   If `assess()` returns no sizing for a paper signal, should the order be
   refused, or fall back to `PAPER_ORDER_UNITS`? This plan refuses — an unsized
   order is what F142 is about — but that is a policy call.
2. **F94 default.** Task 4 returns `1.0` for an unknown regime and leaves sizing
   to the risk manager. The alternative is refusing to size at all until a
   regime is known. Refusing is safer and stops more trades; say which you want.
3. **OANDA.** Task 5 only stops it pretending. Implementing the connector is a
   separate piece of work — worth scheduling deliberately, since live OANDA is
   the stated next milestone.
