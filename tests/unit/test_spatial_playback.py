# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Playback: pause, rewind, accelerate — as a state machine, not an animation.

The rest of capability #5. `Construction` produces the sequence; this decides
which step you are on after some elapsed time at some speed.

No timers, no threads, no event loop. `advance(dt)` is a pure function of the
current state and the elapsed seconds, so every rule below is testable without a
clock and a UI can drive it from `requestAnimationFrame` without the logic living
in a component.

## Clamping at the end is correct here, and that is not a contradiction

`Construction.at()` raises out of range, because "step 999" is a question about
a build that never had 999 steps. Playback is different: running past the end is
what happens every time a video finishes. So it clamps — **and reports
`finished`**, because a player that silently sat on the last frame would be
indistinguishable from one that had stalled.

A seek is not playback: `seek()` raises, matching `at()`.
"""

from __future__ import annotations

import pytest

from ai.spatial.playback import Playback, SpeedRefused
from ai.spatial.timeline import Construction, StageOutOfRange
from ai.spatial.world import Component, ConnectionKind, World

pytestmark = pytest.mark.unit


def _build(n: int = 4) -> Construction:
    w = World(name="w")
    previous = None
    for i in range(n):
        cid = f"c{i}"
        w.add(Component(id=cid, kind="block", material="steel"))
        if previous is not None:
            w.connect(previous, cid, ConnectionKind.SUPPORTS)
        previous = cid
    return Construction(w)


class TestStartingState:
    def test_playback_starts_at_the_beginning_and_paused(self) -> None:
        """Autoplay would mean constructing a Playback has a side effect on what
        the operator sees."""
        p = Playback(_build())
        assert p.step == 0
        assert p.playing is False
        assert p.finished is False

    def test_the_default_speed_is_one_step_per_second(self) -> None:
        assert Playback(_build()).speed == pytest.approx(1.0)


class TestAdvancing:
    def test_a_paused_playback_does_not_advance(self) -> None:
        p = Playback(_build())
        p.advance(10.0)
        assert p.step == 0

    def test_playing_advances_one_step_per_second_at_speed_one(self) -> None:
        p = Playback(_build())
        p.play()
        p.advance(2.0)
        assert p.step == 2

    def test_speed_scales_the_rate(self) -> None:
        p = Playback(_build())
        p.play()
        p.set_speed(2.0)
        p.advance(1.5)
        assert p.step == 3

    def test_fractional_progress_accumulates_rather_than_being_lost(self) -> None:
        """Three advances of 0.4s at speed 1 is 1.2 steps, not zero. Truncating
        each call would make a 60fps caller never move."""
        p = Playback(_build())
        p.play()
        for _ in range(3):
            p.advance(0.4)
        assert p.step == 1

    def test_a_negative_elapsed_time_is_refused(self) -> None:
        """Rewinding by passing negative time would bypass seek's range check."""
        p = Playback(_build())
        p.play()
        with pytest.raises(ValueError, match="negative"):
            p.advance(-1.0)


class TestTheEnd:
    def test_running_past_the_end_stops_at_the_end(self) -> None:
        p = Playback(_build(4))
        p.play()
        p.advance(100.0)
        assert p.step == 4

    def test_reaching_the_end_is_reported_not_silent(self) -> None:
        p = Playback(_build(4))
        p.play()
        p.advance(100.0)
        assert p.finished is True
        assert p.playing is False, "a finished playback that still reports playing has stalled, not ended"

    def test_a_playback_that_has_not_reached_the_end_is_not_finished(self) -> None:
        p = Playback(_build(4))
        p.play()
        p.advance(1.0)
        assert p.finished is False


class TestSpeedControl:
    def test_speed_must_be_positive(self) -> None:
        """Zero is pause, and pause is a separate concept with its own flag.
        Conflating them means `playing` and `speed == 0` disagree about state."""
        with pytest.raises(SpeedRefused, match="positive"):
            Playback(_build()).set_speed(0.0)

    def test_a_negative_speed_is_refused_rather_than_playing_backwards(self) -> None:
        with pytest.raises(SpeedRefused):
            Playback(_build()).set_speed(-1.0)

    def test_a_non_finite_speed_is_refused(self) -> None:
        """Infinite speed would jump to the end; NaN would freeze it, and both
        would look like a bug in the build rather than in the player."""
        for bad in (float("inf"), float("nan")):
            with pytest.raises(SpeedRefused):
                Playback(_build()).set_speed(bad)

    def test_changing_speed_does_not_lose_accumulated_progress(self) -> None:
        p = Playback(_build())
        p.play()
        p.advance(0.6)
        p.set_speed(4.0)
        p.advance(0.1)
        assert p.step == 1


class TestSeeking:
    def test_seeking_moves_to_a_step(self) -> None:
        p = Playback(_build())
        p.seek(3)
        assert p.step == 3

    def test_seeking_out_of_range_raises_like_at_does(self) -> None:
        with pytest.raises(StageOutOfRange):
            Playback(_build(4)).seek(9)

    def test_seeking_backwards_clears_the_finished_flag(self) -> None:
        p = Playback(_build(4))
        p.play()
        p.advance(100.0)
        p.seek(1)
        assert p.finished is False

    def test_seeking_discards_stale_fractional_progress(self) -> None:
        """Carrying 0.9 of a step across a seek would make the next tiny advance
        jump a step the operator did not ask for."""
        p = Playback(_build())
        p.play()
        p.advance(0.9)
        p.seek(0)
        p.advance(0.2)
        assert p.step == 0


class TestPauseAndResume:
    def test_pause_stops_advancing_and_resume_continues(self) -> None:
        p = Playback(_build())
        p.play()
        p.advance(1.0)
        p.pause()
        p.advance(5.0)
        assert p.step == 1
        p.play()
        p.advance(1.0)
        assert p.step == 2

    def test_the_state_at_the_current_step_comes_from_the_construction(self) -> None:
        p = Playback(_build(4))
        p.seek(2)
        assert p.state().components == ("c0", "c1")
