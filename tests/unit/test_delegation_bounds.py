# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§26 — a delegation tree that cannot run away.

I staged this row with the note "recursive delegation does not exist yet to
bound". True, and circular: nothing delegated, so there was nothing to bound,
so it stayed staged. §24's worker boundary gave the bound somewhere to live.

## Why three bounds and not a depth limit

Depth is what people reach for and it catches one failure mode of three. Each
test below is written so that the OTHER two bounds are comfortably satisfied,
which is the only way to show a bound is doing work rather than riding along
behind a stricter neighbour.

## Refusing a child does not fail the tree

The work already done was paid for. Discarding it wastes exactly the spend this
module protects, so a refusal is local: the child does not exist, the parent
carries on, and `refusals()` names what was declined.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from ai.jobs.lineage import (
    DelegationBounds,
    DelegationLedger,
    DelegationRefused,
    Lineage,
)

pytestmark = [pytest.mark.unit]


class _YieldingBounds:
    """A bounds stand-in that releases the GIL when the fan-out limit is READ.

    Test-only, and it touches nothing in the ledger — the ledger only reads
    three attributes off whatever it is given. It exists because the
    check-then-increment window in `admit` is a handful of bytecodes wide, so
    ordinary thread contention never reaches it: a concurrency test that cannot
    reach the race passes whether or not the lock is there, which two earlier
    versions of the test below did.
    """

    def __init__(self, *, max_depth: int, max_fanout: int, max_descendants: int) -> None:
        self.max_depth = max_depth
        self._max_fanout = max_fanout
        self.max_descendants = max_descendants

    @property
    def max_fanout(self) -> int:
        time.sleep(0)
        return self._max_fanout


class TestTheBoundsAreThreeDifferentBounds:
    def test_depth_is_refused_while_fanout_and_total_are_untouched(self) -> None:
        # One child each, all the way down. Fan-out is 1 and the tree is 4
        # nodes, so nothing but the depth bound can be what stops this.
        ledger = DelegationLedger(DelegationBounds(max_depth=3, max_fanout=8, max_descendants=100))
        node = ledger.open_root()
        # Nesting grants, because a grant is charged to the parent IN FULL: a
        # flat 50 at every level exhausts the budget by depth 2, so the
        # DESCENDANTS bound fires first and the depth bound goes untested. The
        # first version of this test did exactly that, and said so by failing.
        for expected, grant in ((1, 20), (2, 10), (3, 5)):
            node = ledger.admit(node, grant=grant)
            assert node.depth == expected

        # Budget nowhere near spent, fan-out of 1 the whole way down: depth is
        # the only bound left that can refuse this.
        assert ledger.remaining(node) == 5
        with pytest.raises(DelegationRefused, match="depth 4"):
            ledger.admit(node)

    def test_fanout_is_refused_while_depth_and_total_are_untouched(self) -> None:
        # Every child sits at depth 1 and the tree is well inside 100 nodes.
        # A depth bound cannot see this, which is the point.
        ledger = DelegationLedger(DelegationBounds(max_depth=3, max_fanout=4, max_descendants=100))
        root = ledger.open_root()
        for _ in range(4):
            ledger.admit(root)

        with pytest.raises(DelegationRefused, match="delegated 4 times"):
            ledger.admit(root)

    def test_total_descendants_is_refused_while_depth_and_fanout_are_untouched(self) -> None:
        # The failure mode neither of the others catches: depth 2 and fan-out 3
        # are each modest, and the tree still outgrows what it was given.
        ledger = DelegationLedger(DelegationBounds(max_depth=5, max_fanout=8, max_descendants=6))
        root = ledger.open_root()
        children = [ledger.admit(root, grant=1) for _ in range(3)]
        assert [c.depth for c in children] == [1, 1, 1]

        # Three children at 1 + a grant of 1 apiece is the whole budget of 6.
        with pytest.raises(DelegationRefused, match="does not fit"):
            ledger.admit(root)

    def test_a_grant_is_charged_in_full_so_two_siblings_cannot_spend_it_twice(self) -> None:
        # Charging only for the child would let each sibling be handed the same
        # remaining budget and each spend it, which is how a bound that reads
        # correctly totals to more than it allows.
        ledger = DelegationLedger(DelegationBounds(max_depth=5, max_fanout=8, max_descendants=10))
        root = ledger.open_root()
        ledger.admit(root, grant=8)  # costs 1 + 8

        assert ledger.remaining(root) == 1
        ledger.admit(root)  # the last one, at cost 1
        with pytest.raises(DelegationRefused, match="does not fit"):
            ledger.admit(root)


class TestItFailsClosed:
    def test_an_unknown_parent_is_refused_rather_than_treated_as_a_root(self) -> None:
        # The whole security of the thing. A node presenting a parent nobody
        # has a record of would, if admitted, receive a fresh budget — which is
        # exactly what a runaway needs.
        ledger = DelegationLedger()
        forged = Lineage(root_id="r", node_id="n", depth=0, parent_id=None, grant=1_000)

        with pytest.raises(DelegationRefused, match="no record"):
            ledger.admit(forged)

    def test_a_root_cannot_be_granted_more_than_the_bounds_allow(self) -> None:
        # Otherwise the ceiling is whatever the caller asks for, and a limit
        # the caller sets is not a limit.
        ledger = DelegationLedger(DelegationBounds(max_descendants=5))
        root = ledger.open_root(grant=10_000)
        assert ledger.remaining(root) == 5

    def test_a_lineage_refuses_impossible_values_at_construction(self) -> None:
        with pytest.raises(ValueError, match="depth"):
            Lineage(root_id="r", node_id="n", depth=-1)
        with pytest.raises(ValueError, match="grant"):
            Lineage(root_id="r", node_id="n", depth=0, grant=-1)
        with pytest.raises(ValueError, match="root id"):
            Lineage(root_id="", node_id="n", depth=0)

    def test_bounds_refuse_zero_and_negative_limits(self) -> None:
        # A max_depth of 0 would refuse every delegation and read, in a report,
        # exactly like a system where nothing delegates.
        for kwargs in ({"max_depth": 0}, {"max_fanout": -1}, {"max_descendants": 0}):
            with pytest.raises(ValueError):
                DelegationBounds(**kwargs)  # type: ignore[arg-type]

    def test_a_bool_is_not_an_integer_grant(self) -> None:
        # `True` is an int in Python and would silently mean "a grant of one".
        ledger = DelegationLedger()
        root = ledger.open_root()
        with pytest.raises(ValueError, match="grant"):
            ledger.admit(root, grant=True)  # type: ignore[arg-type]


class TestARefusalDoesNotFailTheTree:
    def test_the_parent_keeps_its_place_and_can_still_be_asked(self) -> None:
        ledger = DelegationLedger(DelegationBounds(max_depth=3, max_fanout=2, max_descendants=100))
        root = ledger.open_root()
        first = ledger.admit(root)
        ledger.admit(root)

        with pytest.raises(DelegationRefused):
            ledger.admit(root)

        # The tree is intact rather than poisoned by the refusal: the child
        # admitted before it is still known to the ledger, and is refused on
        # its OWN terms — an empty grant — rather than as an unknown parent.
        assert ledger.remaining(first) == 0
        with pytest.raises(DelegationRefused, match="does not fit"):
            ledger.admit(first)
        assert {r.bound for r in ledger.refusals()} == {"fanout", "descendants"}

    def test_every_refusal_is_recorded_with_the_bound_that_caused_it(self) -> None:
        # A silently dropped child is a plan that ran differently from the plan
        # that was written — `unknown_dependencies()` makes the same argument.
        ledger = DelegationLedger(DelegationBounds(max_depth=1, max_fanout=1, max_descendants=1))
        root = ledger.open_root()
        child = ledger.admit(root)

        with pytest.raises(DelegationRefused):
            ledger.admit(root)  # fan-out
        with pytest.raises(DelegationRefused):
            ledger.admit(child)  # depth

        bounds_hit = {r.bound for r in ledger.refusals()}
        assert bounds_hit == {"fanout", "depth"}
        assert all(r.detail for r in ledger.refusals())

    def test_reading_the_refusals_does_not_clear_them(self) -> None:
        ledger = DelegationLedger(DelegationBounds(max_depth=1, max_fanout=1, max_descendants=1))
        root = ledger.open_root()
        ledger.admit(root)
        with pytest.raises(DelegationRefused):
            ledger.admit(root)
        assert len(ledger.refusals()) == 1
        assert len(ledger.refusals()) == 1


class TestItHoldsUnderConcurrency:
    def test_two_threads_delegating_at_once_cannot_exceed_the_fanout(self) -> None:
        """The bound must hold when the runner's worker threads admit at once.

        Two jobs delegating against an unguarded counter is how a fan-out bound
        becomes a suggestion, and it is the kind of defect that passes every
        single-threaded test.

        Two earlier versions of this test passed with the lock REMOVED, which
        makes them tests of nothing. Raw thread contention was not enough:
        `admit` runs so few bytecodes between reading `children` and
        incrementing it that sixteen threads never landed inside the window,
        even with the switch interval at a microsecond.

        So the window is widened where the race actually is. `_YieldingBounds`
        releases the GIL inside the fan-out CHECK — the read — which is the
        exact point an unlocked ledger loses. It changes nothing about the code
        under test; it only makes the existing race reachable in finite time.
        """
        bounds = _YieldingBounds(max_depth=3, max_fanout=8, max_descendants=10_000)
        for attempt_number in range(10):
            ledger = DelegationLedger(bounds)
            root = ledger.open_root()
            admitted: list[Lineage] = []
            guard = threading.Lock()
            start = threading.Barrier(12)

            def attempt(ledger: DelegationLedger = ledger, root: Lineage = root) -> None:
                start.wait()
                for _ in range(20):
                    try:
                        child = ledger.admit(root)
                    except DelegationRefused:
                        return
                    with guard:
                        admitted.append(child)

            threads = [threading.Thread(target=attempt) for _ in range(12)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(admitted) == 8, f"fan-out of 8 admitted {len(admitted)} children on attempt {attempt_number}"
            assert len({c.node_id for c in admitted}) == 8, "two children were given the same id"


class TestTheReportIsMeasured:
    def test_it_counts_what_happened_rather_than_what_was_intended(self) -> None:
        ledger = DelegationLedger(DelegationBounds(max_depth=2, max_fanout=2, max_descendants=10))
        root = ledger.open_root()
        child = ledger.admit(root, grant=2)
        ledger.admit(child)

        report = ledger.report()
        assert report["nodes"] == 3
        assert report["max_depth_seen"] == 2
        assert report["refused"] == 0


class TestTheBoundSurvivesTheProcessBoundary:
    """A ledger is per-process. A grant is what crosses.

    These run a real child, because the claim being made is precisely that a
    fresh interpreter with an empty ledger still cannot overspend. Asserted in
    the parent against what the child reports back.
    """

    def test_a_child_may_delegate_exactly_what_it_was_granted(self) -> None:
        from ai.jobs.isolation import TaskContract, run_isolated
        from ai.jobs.lineage import get_ledger, reset_for_testing

        reset_for_testing()
        try:
            root = get_ledger().open_root()
            parent = TaskContract(
                entrypoint="tests.support.isolated_tasks:delegate_until_refused",
                operator="alice",
                lineage=root,
            )
            child = parent.delegate("tests.support.isolated_tasks:delegate_until_refused", grant=3)
            outcome = run_isolated(child)

            assert outcome.state == "succeeded", outcome.error
            # Three, and then a refusal naming the budget. Not four, and not
            # the parent's whole allowance of 24.
            assert outcome.result["admitted"] == 3
            assert "does not fit" in outcome.result["refused"]
        finally:
            reset_for_testing()

    def test_a_child_granted_nothing_cannot_delegate_at_all(self) -> None:
        # The default. Delegation does not propagate unless somebody said so in
        # the call that created the child.
        from ai.jobs.isolation import TaskContract, run_isolated
        from ai.jobs.lineage import get_ledger, reset_for_testing

        reset_for_testing()
        try:
            root = get_ledger().open_root()
            parent = TaskContract(
                entrypoint="tests.support.isolated_tasks:delegate_until_refused",
                operator="alice",
                lineage=root,
            )
            outcome = run_isolated(parent.delegate("tests.support.isolated_tasks:delegate_until_refused"))
            assert outcome.state == "succeeded", outcome.error
            assert outcome.result["admitted"] == 0
        finally:
            reset_for_testing()

    def test_a_contract_claiming_a_lineage_this_process_never_issued_is_not_run(self) -> None:
        # Fail closed at the boundary as well as in the ledger. A replayed or
        # forged contract must not get a fresh budget by arriving from outside.
        from ai.jobs.isolation import TaskContract, run_isolated
        from ai.jobs.lineage import Lineage, reset_for_testing

        reset_for_testing()
        try:
            forged = Lineage(root_id="r", node_id="nope", depth=0, parent_id=None, grant=10_000)
            outcome = run_isolated(
                TaskContract(
                    entrypoint="tests.support.isolated_tasks:succeed",
                    operator="alice",
                    lineage=forged,
                )
            )
            assert outcome.state == "failed"
            assert "no record" in outcome.error
        finally:
            reset_for_testing()

    def test_a_task_with_no_lineage_runs_but_cannot_delegate(self) -> None:
        # Everything that ran before §26 keeps running. Isolation stays opt-in
        # and delegation stays opt-in on top of it.
        from ai.jobs.isolation import TaskContract, run_isolated
        from ai.jobs.lineage import DelegationRefused, reset_for_testing

        reset_for_testing()
        try:
            plain = TaskContract(entrypoint="tests.support.isolated_tasks:succeed", operator="alice")
            outcome = run_isolated(plain)
            assert outcome.state == "succeeded", outcome.error

            with pytest.raises(DelegationRefused, match="no lineage"):
                plain.delegate("tests.support.isolated_tasks:succeed")
        finally:
            reset_for_testing()


class TestTheBoundaryHasACallerNow:
    """§24's `run_isolated` was imported by nothing outside its own tests.

    That is `hopefx-dead-controls` inside the work that closed a row about
    isolation, and the registry could not catch it: `verify()` resolves an
    evidence locator and has no opinion about whether anything imports it.
    """

    def test_a_job_can_be_run_behind_the_process_boundary(self) -> None:
        import time as _time

        from ai.jobs.isolation import TaskContract
        from ai.jobs.runner import TERMINAL_STATES, JobRunner

        runner = JobRunner()
        try:
            contract = TaskContract(
                entrypoint="tests.support.isolated_tasks:report_pid",
                operator="alice",
            )
            job_id = runner.submit_isolated(prompt="heavy work", contract=contract)

            deadline = _time.time() + 30.0
            while _time.time() < deadline:
                if runner.get(job_id, operator="alice").state in TERMINAL_STATES:
                    break
                _time.sleep(0.02)

            job = runner.get(job_id, operator="alice")
            assert job.state == "succeeded", job.error
            # The claim, measured: it really ran somewhere else.
            assert job.result != os.getpid()
        finally:
            runner.shutdown()

    def test_the_job_belongs_to_the_operator_named_in_the_contract(self) -> None:
        # The scoping a P0 was fixed for. An isolated result belongs to the
        # operator whose contract produced it, and to nobody else.
        from ai.jobs.isolation import TaskContract
        from ai.jobs.runner import JobRunner

        runner = JobRunner()
        try:
            contract = TaskContract(entrypoint="tests.support.isolated_tasks:succeed", operator="bob")
            job_id = runner.submit_isolated(prompt="p", contract=contract)
            assert runner.get(job_id, operator="bob").operator == "bob"
            # KeyError, and the same KeyError a missing job raises: telling the
            # two apart would make this an oracle for guessing which job ids
            # exist. The runner already holds that rule.
            with pytest.raises(KeyError):
                runner.get(job_id, operator="alice")
        finally:
            runner.shutdown()

    def test_an_isolated_task_that_dies_fails_the_job_rather_than_returning_nothing(self) -> None:
        import time as _time

        from ai.jobs.isolation import TaskContract
        from ai.jobs.runner import TERMINAL_STATES, JobRunner

        runner = JobRunner()
        try:
            contract = TaskContract(entrypoint="tests.support.isolated_tasks:die_hard", operator="alice")
            job_id = runner.submit_isolated(prompt="p", contract=contract)
            deadline = _time.time() + 30.0
            while _time.time() < deadline:
                if runner.get(job_id, operator="alice").state in TERMINAL_STATES:
                    break
                _time.sleep(0.02)

            job = runner.get(job_id, operator="alice")
            assert job.state == "failed"
            assert job.error
        finally:
            runner.shutdown()
