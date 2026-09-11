# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Playback — pause, rewind, accelerate. A state machine, not an animation.

The rest of capability #5. `Construction` produces the sequence; this decides
which step you are on after some elapsed time at some speed.

**No timers, no threads, no event loop.** `advance(dt)` is a pure function of the
current state and the elapsed seconds. That keeps every rule here testable
without a clock, and lets a UI drive it from `requestAnimationFrame` without the
logic ending up inside a component where nothing can reach it.

## Clamping at the end is correct here, and that is not a contradiction

`Construction.at()` raises out of range, because "step 999" is a question about a
build that never had 999 steps — answering it with a finished building is a
confident answer to a nonsense question.

Playback is different: running past the end is what happens every time a video
finishes. So it clamps — **and sets `finished`**, because a player that silently
sat on the last frame would be indistinguishable from one that had stalled, and
"it stopped moving" is the first symptom of both.

A seek is not playback, so `seek()` raises like `at()` does.

## Speed is positive, finite, and never zero

Zero is pause, and pause has its own flag. Conflating them means `playing` and
`speed == 0` can disagree about what the player is doing. Infinity would jump to
the end and `NaN` would freeze it — both of which look like a bug in the build
rather than in the player, which is the worst place for a bug to appear to be.
"""

from __future__ import annotations

import math

from ai.spatial.timeline import Construction, WorldState

__all__ = ["Playback", "SpeedRefused"]


class SpeedRefused(ValueError):
    """A playback rate that is not a rate."""


class Playback:
    """Where in a build you are, and how fast you are moving through it."""

    def __init__(self, construction: Construction, *, speed: float = 1.0) -> None:
        self._construction = construction
        self._last_step = len(construction.stages())
        self._step = 0
        self._carry = 0.0  # fractional progress toward the next step
        self._speed = 1.0
        self.playing = False
        self.finished = False
        self.set_speed(speed)

    # ── state ───────────────────────────────────────────────────────────────

    @property
    def step(self) -> int:
        return self._step

    @property
    def speed(self) -> float:
        return self._speed

    def state(self) -> WorldState:
        """What exists at the current step."""
        return self._construction.at(self._step)

    # ── transport ───────────────────────────────────────────────────────────

    def play(self) -> None:
        self.playing = True

    def pause(self) -> None:
        self.playing = False

    def set_speed(self, speed: float) -> None:
        if not isinstance(speed, (int, float)) or isinstance(speed, bool) or not math.isfinite(speed):
            raise SpeedRefused(f"speed must be a finite number, got {speed!r}")
        if speed <= 0:
            raise SpeedRefused(f"speed must be positive, got {speed!r}; use pause() to stop")
        self._speed = float(speed)

    def seek(self, step: int) -> None:
        """Jump to a step, refusing one this build does not have.

        Fractional progress is discarded: carrying 0.9 of a step across a seek
        would make the next tiny advance jump a step nobody asked for.
        """
        self._construction.at(step)  # raises StageOutOfRange
        self._step = step
        self._carry = 0.0
        self.finished = step >= self._last_step

    def advance(self, elapsed_seconds: float) -> None:
        """Move forward by `elapsed_seconds` of wall time at the current speed.

        Fractional progress accumulates rather than being truncated per call —
        otherwise a caller ticking at 60fps would never move at all.
        """
        if elapsed_seconds < 0:
            raise ValueError(f"elapsed time cannot be negative ({elapsed_seconds!r}); use seek() to go back")
        if not self.playing or self.finished:
            return

        self._carry += elapsed_seconds * self._speed
        whole, self._carry = divmod(self._carry, 1.0)
        self._step += int(whole)

        if self._step >= self._last_step:
            self._step = self._last_step
            self._carry = 0.0
            self.finished = True
            self.playing = False
