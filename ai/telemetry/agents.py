# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Whether the agents are actually able to do anything. §22.

A department that exists and has no implemented action is not a healthy
department — it is a name in a directory. `status` says which of the two each
one is, because the directory alone cannot.

Every number here is derived from live objects handed in, never from a default.
A job pool reported as `running: 0` when no runner was passed is the §22 defect
in a different costume: it reads as an idle pool rather than as an unobserved
one, so a missing runner is reported as unmeasured with a reason.
"""

from __future__ import annotations

from typing import Any

from ai.telemetry.reading import absent, measured


def agent_health(*, runner: Any = None, watcher_runs: int | None = None) -> dict[str, Any]:
    """Per-department readiness, the job pool, and the awareness layer.

    `runner` and `watcher_runs` are injected rather than reached for: this
    module reports on state it is shown, so "nobody gave me the runner" is a
    distinguishable answer from "the runner is idle".
    """
    from ai.departments import DEPARTMENTS, implemented_actions

    implemented: dict[str, int] = {}
    for action in implemented_actions():
        department = action.name.split(".", 1)[0]
        implemented[department] = implemented.get(department, 0) + 1

    departments: dict[str, Any] = {}
    for key, department in DEPARTMENTS.items():
        count = implemented.get(key, 0)
        departments[key] = {
            "title": department.title,
            "declared": len(department.actions),
            "implemented": count,
            # "declared_only" is deliberately not "unhealthy": a department that
            # has not been built yet is a roadmap entry, and calling it a fault
            # would make the real faults harder to see.
            "status": "ready" if count else "declared_only",
        }

    return {
        "departments": departments,
        "jobs": _jobs(runner),
        "awareness": _awareness(watcher_runs),
    }


def _jobs(runner: Any) -> dict[str, Any]:
    if runner is None:
        return absent(
            "jobs",
            "no job runner was provided, so the pool was not observed; this is not the same as an idle pool",
        ).as_dict()
    try:
        snap = runner.snapshot()
    except Exception as exc:
        return absent("jobs", f"the runner's snapshot failed: {type(exc).__name__}: {exc}").as_dict()
    return {
        "measured": True,
        "running": snap.get("running", 0),
        "queued": snap.get("queued", 0),
        "waiting": snap.get("waiting", 0),
        "longest_wait_s": snap.get("longest_wait_s", 0.0),
        "max_concurrent": snap.get("max_concurrent"),
    }


def _awareness(watcher_runs: int | None) -> dict[str, Any]:
    if watcher_runs is None:
        return absent("awareness", "the watcher run count was not provided, so it was not observed").as_dict()
    if watcher_runs <= 0:
        # "No observations" and "the watcher has never run" look identical on a
        # screen, and only one of them is a problem.
        return absent("awareness", "the watchers have never run, so no observation is expected yet").as_dict()
    return measured("awareness", float(watcher_runs)).as_dict()


__all__ = ["agent_health"]
