"""AOS-EVID-046 — alert firing, delivery and acceptance are three distinct stages.

The AOS register records this invariant as ABSENT:

    Spec §17: alert firing, notification delivery and external acceptance are
    distinct stages. `verify_notification_delivered` exists but collapses the
    ladder into one boolean.

Measured before writing this, and it is worse than the register says:

  1. `verify_notification_delivered(0, 0, max_failures)` returns NO VIOLATION.
     A pipeline where NOTHING FIRED AT ALL reads as perfectly healthy, because
     `failures = sent - delivered` is 0. Silence and success are the same number
     to it — the F176 "measurement that cannot fail" shape.
  2. It has NO production caller. `grep` finds it only in two assertions in
     tests/unit/test_invariants_platform.py. It is itself a dead control.
  3. `AlertEngine._stats` counts `total_alerts_created` and `total_triggers` and
     nothing else, so there were no fired/delivered numbers for it to read even
     if it had been wired.

Why this matters here rather than in the abstract. `notifications/alert_engine.py`
already knows the first two rungs apart — its own docstring says of the return
value: "False means it exists in the log and nowhere else — **never treat that
as sent**." That distinction was learned the expensive way: F159 (the delivery
guard and the delivery were the same branch, so every alert stopped at the log
line) and F248 (three alert call sites passed arguments the target rejects, so a
tripped Sharpe circuit breaker, an automatic model rollback and a position-drift
halt each notified nobody). In both, a one-boolean health check would have read
green.

The third rung — external ACCEPTANCE — is deliberately not fabricated here.
Nothing in this codebase observes a channel's acknowledgement, so `accepted=None`
means NOT OBSERVED and the predicate says so. Defaulting it to `delivered` would
be exactly the conflation this invariant exists to forbid.

`verify_notification_delivered` is left alone. Its question — "did delivery lose
messages?" — is a legitimate one, and 0 sent genuinely means 0 lost. The defect
is that nothing asked the OTHER questions; this adds the predicate that does.
"""

from __future__ import annotations

import pytest

from invariants import integrations as integ


def _messages(violations) -> str:
    return " | ".join(v.message for v in violations)


# ── positive controls ─────────────────────────────────────────────────────────


def test_the_predicate_exists_and_a_healthy_ladder_is_clean():
    """Without this, every 'it violates' assertion below could pass vacuously."""
    assert hasattr(integ, "verify_alert_evidence_ladder"), "predicate not defined"
    assert integ.verify_alert_evidence_ladder(fired=10, delivered=10, accepted=10) == []


def test_the_old_predicate_still_answers_its_own_question():
    """Not redefined. 'Did delivery lose messages?' is legitimate on its own."""
    assert integ.verify_notification_delivered(100, 100, 5) == []
    assert integ.verify_notification_delivered(100, 50, 5)


# ── rung 1: fired -> delivered ────────────────────────────────────────────────


def test_fired_but_nothing_delivered_is_a_violation():
    """The F159/F248 shape: the alert reached the log and nowhere else."""
    v = integ.verify_alert_evidence_ladder(fired=7, delivered=0, accepted=0)
    assert v, "7 alerts fired and 0 delivered was reported as healthy"
    assert "deliver" in _messages(v).lower()


def test_delivered_cannot_exceed_fired():
    """More delivered than fired is a counting bug, not good news."""
    v = integ.verify_alert_evidence_ladder(fired=3, delivered=9, accepted=0)
    assert v, "delivered > fired was accepted"


# ── rung 2: delivered -> accepted ─────────────────────────────────────────────


def test_accepted_cannot_exceed_delivered():
    v = integ.verify_alert_evidence_ladder(fired=9, delivered=3, accepted=7)
    assert v, "accepted > delivered was accepted"


def test_unobserved_acceptance_is_reported_as_unobserved_not_as_success():
    """`accepted=None` must not silently become `delivered`.

    This is the whole invariant: a rung nobody measured is not a rung that
    passed. It is reported, and it is NOT the same result as observing that
    every delivered alert was accepted.
    """
    unobserved = integ.verify_alert_evidence_ladder(fired=5, delivered=5, accepted=None)
    observed = integ.verify_alert_evidence_ladder(fired=5, delivered=5, accepted=5)
    assert unobserved != observed, "an unmeasured rung was reported as a passing one"
    assert unobserved, "acceptance was never observed and nothing said so"
    assert "accept" in _messages(unobserved).lower()


# ── the dead-pipeline hole ────────────────────────────────────────────────────


def test_silence_is_not_health_when_alerts_were_expected():
    """(0, 0) is what a completely dead alerting pipeline looks like.

    verify_notification_delivered returns [] for it — measured. When the caller
    can say alerts WERE expected, nothing having fired is the failure, not the
    baseline.
    """
    assert integ.verify_alert_evidence_ladder(fired=0, delivered=0, accepted=0, expected_fired=4), (
        "4 alerts were expected, 0 fired, and that was reported as healthy"
    )


def test_a_genuinely_quiet_period_is_still_clean():
    """The counterweight. Nothing expected and nothing fired is not a defect —
    otherwise the predicate cries wolf and operators learn to ignore it."""
    assert integ.verify_alert_evidence_ladder(fired=0, delivered=0, accepted=0, expected_fired=0) == []


# ── it names the rung ─────────────────────────────────────────────────────────


def test_it_says_which_rung_broke_rather_than_returning_one_boolean():
    """The register's actual complaint: the ladder was collapsed."""
    v = integ.verify_alert_evidence_ladder(fired=10, delivered=2, accepted=1)
    assert v, "8 undelivered and 1 unaccepted was reported as healthy"
    msg = _messages(v)
    assert "10" in msg and "2" in msg, f"the counts are not in the message: {msg}"


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf")])
def test_a_nonsense_count_does_not_pass_silently(bad):
    """A NaN compared with > is False, so a broken counter would read healthy."""
    assert integ.verify_alert_evidence_ladder(fired=bad, delivered=0, accepted=0), (
        f"fired={bad!r} was accepted as a valid count"
    )
