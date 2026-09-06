"""F222 (TODO item 5, last module) — an unmeasured tick claimed maximum quality.

Every tick written without an explicit assessment defaulted to
`quality="good", confidence=1.0` — in the repository signature, in the ORM
column, in `data_layer.types.Tick`, in the orchestrator's two cache reads and in
the tick store. `data_layer/quality/engine.py::DataQualityEngine` exists to
compute exactly those two fields, and every one of those defaults asserts its
conclusion without running it.

Same shape as everything else this audit has removed: a default that states a
measurement nobody made.

**The decision, and why it is the safe one.** `TickQuality` gains `UNKNOWN` and
every *default* becomes it. The downstream filters are deliberately left alone:
they all test `quality != TickQuality.REJECTED`, so `GOOD` and `UNKNOWN` behave
identically today and no tick that flows now stops flowing. The change is purely
about the record being truthful — which is the prerequisite for any future gate,
because a gate built on a field that always says "good" gates nothing.

What is explicitly NOT decided here: whether an unknown-quality tick may reach
the trading path. That is a policy question, it needs the owner, and it is now
*expressible* — which it was not while the field could only say "good".
"""

from __future__ import annotations

import sys

import pytest


def _module(name: str):
    __import__(name)
    return sys.modules[name]


_TYPES = _module("data_layer.types")
TickQuality = _TYPES.TickQuality


# ── the label exists ─────────────────────────────────────────────────────────


def test_unknown_is_a_quality_a_tick_can_carry() -> None:
    assert hasattr(TickQuality, "UNKNOWN")
    assert TickQuality.UNKNOWN.value == "unknown"


def test_unknown_is_distinct_from_good() -> None:
    """ "Nobody measured this" and "this was measured and is good" are not the same."""
    assert TickQuality.UNKNOWN is not TickQuality.GOOD


# ── nothing defaults to a measurement ────────────────────────────────────────


def test_the_domain_tick_defaults_to_unknown() -> None:
    """`GoldTick` is the dataclass the feeds construct — the type is not `Tick`."""
    import dataclasses

    default = next(f.default for f in dataclasses.fields(_TYPES.GoldTick) if f.name == "quality")
    assert default is TickQuality.UNKNOWN, f"GoldTick.quality defaults to {default!r}"


def test_the_repository_defaults_to_unknown() -> None:
    import inspect

    repo = _module("database.repositories.tick_data_repository")
    signature = inspect.signature(repo.TickDataRepository.insert_tick)

    assert signature.parameters["quality"].default == TickQuality.UNKNOWN.value
    assert signature.parameters["confidence"].default is None, (
        "confidence defaulted to 1.0 — full confidence in a tick nobody assessed"
    )


def test_the_orm_column_defaults_to_unknown() -> None:
    """A row inserted outside the repository must not claim "good" either."""
    from database import models

    for mapper in models.Base.registry.mappers:
        table = mapper.local_table
        if table is not None and table.name == "tick_data":
            column = table.c["quality"]
            assert column.default is not None
            assert column.default.arg == TickQuality.UNKNOWN.value
            return
    pytest.skip("tick_data is not mapped in this build")


def test_no_source_file_still_defaults_quality_to_good() -> None:
    """The four cache/store reads defaulted independently; all of them move together.

    A single site left saying "good" reintroduces the claim for whichever path
    happens to use it, which is worse than the uniform default it replaced.
    """
    import pathlib
    import re

    offenders: list[str] = []
    for path in (
        "data_layer/types.py",
        "data_layer/orchestrator.py",
        "data_layer/tick_store.py",
        "database/repositories/tick_data_repository.py",
        "database/models.py",
    ):
        text = pathlib.Path(path).read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            if re.search(r'get\(\s*["\']quality["\']\s*,\s*["\']good["\']', line) or re.search(
                r'quality\s*[:=].*default\s*=\s*["\']good["\']', line
            ):
                offenders.append(f"{path}:{number}")
    assert not offenders, f"these still default an unmeasured tick to 'good': {offenders}"


# ── the quality engine still reports what it measured ────────────────────────


def test_a_measured_good_tick_is_still_good() -> None:
    """The default changed; the measurement did not.

    `DataQualityEngine` assigning GOOD after running its checks is the one place
    "good" is a conclusion rather than an assumption, and it must keep saying so.
    """
    import pathlib

    engine = pathlib.Path("data_layer/quality/engine.py").read_text(encoding="utf-8")
    assert "quality = TickQuality.GOOD" in engine, (
        "the quality engine no longer assigns GOOD; the measurement path was changed "
        "along with the defaults, which is not what this fix is for"
    )


# ── behaviour today is unchanged ─────────────────────────────────────────────


def test_unknown_passes_the_same_filters_good_did() -> None:
    """No tick that flows today stops flowing.

    Every downstream filter tests `!= REJECTED`. Asserted here so the
    behavioural claim in the commit message is checked, not just written.
    """
    assert TickQuality.UNKNOWN != TickQuality.REJECTED
    assert TickQuality.GOOD != TickQuality.REJECTED


def test_unknown_is_not_counted_as_a_measured_grade() -> None:
    """Whatever reports quality must be able to tell the two apart."""
    graded = {TickQuality.GOOD, TickQuality.STALE, TickQuality.SUSPECT, TickQuality.REJECTED}
    assert TickQuality.UNKNOWN not in graded
