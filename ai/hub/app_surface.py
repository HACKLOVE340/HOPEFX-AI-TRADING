# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""What the platform can do, described to the AI by the platform itself.

This answers an architectural question rather than adding a feature: is the AI a
component inside the application, or is the application a set of capabilities
the AI can see? §4 and §31 want the second — "the AI understands the situation
and constructs the environment required to help the user" — and the difference
is not cosmetic.

An AI that only knows the endpoints somebody remembered to wire is permanently
one commit behind its own platform, and the gap is silent: nothing fails, the AI
is simply ignorant of a feature that shipped last week. Sixty-five routers are
mounted here. A hand-maintained list of their endpoints would be wrong within a
day, and wrong in the direction nobody notices.

So this is DERIVED from the running application's route table. Adding a router
tomorrow makes it visible here with nobody editing anything.

## Discovery is not capability

**Knowing that `POST /api/trading/order` exists must not mean the AI can call
it.** Execution stays behind `ai/tools/bus.py` and its fail-closed permission
gate; this reports what the PLATFORM can do, never what the AI may do.

Every write is `invokable=False` unless a tool was explicitly registered for it
on the bus — and today none is, so every write in this catalogue is visible and
unreachable. That is the correct state, not a gap: the catalogue is a map, and a
map that implied permission would read as a menu.

`summary()` therefore reports `visible` and `invokable` as two numbers. Merging
them is exactly how a map becomes a menu.

## What it deliberately does not carry

No request bodies, no parameter schemas, no examples. A description of the
platform is not a copy of its inputs, and a catalogue that quoted request models
would eventually quote one containing a credential field name and a sample
value. Path, method, mode, area, auth, and the docstring's first line.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Methods that change something. Everything else is a read.
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Never described, whatever the route table says. These are transport and
#: documentation plumbing; listing them would pad the catalogue with entries
#: that mean nothing to an operator or to a model.
_SKIP_PREFIXES = ("/openapi", "/docs", "/redoc", "/static", "/assets", "/favicon")

#: Shorter than this and a word is punctuation with letters — "of", "an", "id".
_MIN_SEARCH_WORD = 3

#: Words that match everything and therefore distinguish nothing. Without this,
#: "current" alone matches a third of the docstrings in this repository.
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "these",
        "those",
        "from",
        "into",
        "current",
        "currently",
        "latest",
        "get",
        "show",
        "give",
        "tell",
        "please",
        "what",
        "which",
        "when",
        "where",
        "how",
        "any",
        "all",
        "some",
        "our",
        "its",
        "are",
        "was",
        "were",
        "has",
        "have",
        "had",
        "can",
        "could",
        "would",
        "should",
        "about",
        "against",
        "over",
        "under",
        "than",
        "then",
        "there",
        "here",
        "now",
        "return",
        "returns",
        "list",
        "data",
        "info",
        "information",
        "status",
        "check",
    }
)


@dataclass(frozen=True)
class AppCapability:
    """One thing the platform can do."""

    method: str
    path: str
    #: `read` or `write`. The single most important field here.
    mode: str
    #: The area of the product, from the path — `trading`, `ai-core`, `risk`.
    area: str
    #: First line of the handler's docstring, when it has one.
    summary: str = ""
    #: The role or dependency the route requires, when it declares one.
    auth: str = ""
    #: The tool name that would have to be registered for the AI to invoke it.
    tool: str = ""
    #: Whether the AI can actually call it. False for every write with no
    #: registered tool, which today is all of them.
    invokable: bool = False


@dataclass
class AppSurface:
    entries: list[AppCapability] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """Two numbers, never one.

        `visible` is what the AI can reason about. `invokable` is what it can
        do. Reporting a single figure would let a reader conclude the second
        from the first, which is the misunderstanding this whole module is
        arranged to prevent.
        """
        reads = sum(1 for e in self.entries if e.mode == "read")
        writes = len(self.entries) - reads
        return {
            "visible": len(self.entries),
            "invokable": sum(1 for e in self.entries if e.invokable),
            "reads": reads,
            "writes": writes,
            # Without this, `invokable: 0` reads as "the bus is empty" when what
            # it means is "the bus has seventeen tools and none of them is an
            # HTTP route". Those are different facts and an operator asking why
            # the AI cannot do anything deserves the second one.
            "tools_registered": len(_bus_handlers()),
            "areas": sorted({e.area for e in self.entries if e.area}),
        }

    def by_area(self, area: str) -> list[AppCapability]:
        return [e for e in self.entries if e.area == area]

    def search(self, phrase: str, limit: int = 12) -> list[AppCapability]:
        """Find capabilities a phrase might be about. For the AI, not for a UI.

        ## Stopwords, and why they are not optional here

        The first version scored any word of three or more letters, so "check
        the current drawdown against risk limits" matched 850 of 2,234 routes —
        "current" alone appears in a third of the docstrings in this codebase.
        A result set that large is the same as no result set: whatever is put in
        front of a model is arbitrary. This repository has already shipped that
        exact defect once, in `Scene.resolve`, where "nothing like this" matched
        a panel titled "gold price THIS session".

        ## The path outranks the prose

        A word in `/api/risk/limits` is a much stronger signal than the same
        word in a docstring that happens to mention risk, so it scores higher.
        Ties break on path then method rather than on list order, because a
        catalogue that returns different rows for the same question depending
        on router registration order is not something to reason from.
        """
        words = [w for w in phrase.lower().split() if len(w) >= _MIN_SEARCH_WORD and w not in _STOPWORDS]
        if not words:
            return []

        scored: list[tuple[int, str, str, AppCapability]] = []
        for entry in self.entries:
            path = entry.path.lower()
            summary = entry.summary.lower()
            area = entry.area.lower()
            score = 0
            for word in words:
                if word in path:
                    score += 3
                if word in area:
                    score += 2
                if word in summary:
                    score += 1
            if score:
                scored.append((-score, entry.path, entry.method, entry))
        scored.sort(key=lambda row: row[:3])
        return [row[3] for row in scored[:limit]]

    def as_prompt(self, phrase: str, limit: int = 12) -> str:
        """The catalogue as a model can actually consume it.

        Two thousand two hundred routes do not fit in a prompt, and pasting a
        truncated prefix of them would silently hide whole areas of the
        platform. So the AI is given what its current goal is about, and told
        plainly that seeing a route is not permission to call it — `permitted`
        is a separate, much shorter list, and the two must never read as one.
        """
        hits = self.search(phrase, limit=limit)
        if not hits:
            return "No platform capability matches this goal."
        lines = [f"{e.method} {e.path} [{e.mode}] {e.summary}".rstrip() for e in hits]
        return (
            "Platform capabilities related to this goal (reference only — "
            "you cannot call these; only the permitted actions are callable):\n" + "\n".join(lines)
        )


def _area_of(path: str) -> str:
    parts = [p for p in path.split("/") if p and not p.startswith("{")]
    if parts and parts[0] == "api":
        parts = parts[1:]
    return parts[0] if parts else ""


def _auth_of(route: Any) -> str:
    """The role a route requires, read from its dependencies.

    Best-effort by design: FastAPI dependencies are callables, and their names
    are the only stable thing to read without importing every module they live
    in. An empty string means "not declared here", never "open" — the route's
    own dependency still runs whatever this says.
    """
    names: list[str] = []
    for dependency in getattr(getattr(route, "dependant", None), "dependencies", []) or []:
        call = getattr(dependency, "call", None)
        name = getattr(call, "__name__", "")
        if name and name not in names:
            names.append(name)
    for param in getattr(getattr(route, "dependant", None), "query_params", []) or []:
        _ = param  # signature only; no values are read
    return ",".join(names[:3])


def _bus_handlers() -> dict[int, str]:
    """Handler object → tool name, for tools the bus can actually dispatch.

    Keyed by `id()` of the handler rather than by its name. Name-matching would
    be a guess — a route function called `place_order` and a bus action called
    `markets_execution.shadow_place_order` are unrelated objects that happen to
    share a word — and a guess in this direction marks a write invokable that
    is not. Identity cannot be wrong: either the same function is on both sides
    or the route is unreachable from the bus.

    Read from `implemented_actions()`, which is what `build_tool_bus()`
    registers, so this tracks the real bus without constructing one.
    """
    try:
        from ai.departments import implemented_actions

        return {id(action.handler): action.name for action in implemented_actions()}
    except Exception:
        # A bus that cannot be read is a bus that grants nothing. Failing closed
        # here is the difference between a map and a menu.
        logger.debug("ai.hub.app_surface: tool registry unreadable; treating every write as unreachable")
        return {}


def _build_app() -> Any:
    """A FastAPI instance with every router this deployment mounts.

    Prefers an application the process has already built: `app.py` is what
    production runs, and reading its route table costs nothing and cannot
    disagree with the routes actually serving traffic. Only when no such app
    exists — a test, a worker — is a fresh one registered.

    Registering a fresh one is not free of side effects: `register_routers`
    clears `core.router_registry._registered_routes`, the dedup bookkeeping for
    a registration pass. That set is only read while routers are being mounted,
    so clearing it after startup changes nothing about a running app; doing it
    *during* someone else's registration pass would, which is the second reason
    to prefer an app that is already built.
    """
    import sys

    existing = getattr(sys.modules.get("app"), "app", None)
    if existing is not None and hasattr(existing, "routes"):
        return existing

    from fastapi import FastAPI

    from config.feature_flags import flags
    from core.router_registry import register_routers

    fresh = FastAPI()
    try:
        register_routers(fresh, flags)
    except Exception:
        # A partial catalogue is worth more than none, and silence here would be
        # the failure mode this module exists to avoid — so it is logged loudly
        # rather than swallowed.
        logger.warning(
            "ai.hub.app_surface: some routers did not mount; the catalogue is partial",
            exc_info=True,
        )
    return fresh


def describe_app(app: Any = None) -> AppSurface:
    """Enumerate what the running application can do.

    Walks the route table with `core.router_registry.iter_api_routes`, never
    `app.routes` directly. Starlette no longer flattens an included router's
    routes onto `app.routes` at `include_router()` time — each inclusion is an
    opaque wrapper expanded only at dispatch — so reading `app.routes` naively
    sees almost nothing, and reports a handful of endpoints for a platform with
    sixty-five routers. That failure is silent, which is exactly the kind this
    module exists to prevent.
    """
    from core.router_registry import iter_api_routes

    if app is None:
        app = _build_app()

    handlers = _bus_handlers()
    seen: set[tuple[str, str]] = set()
    entries: list[AppCapability] = []

    for route in iter_api_routes(getattr(app, "routes", [])):
        path = str(getattr(route, "path", "") or "")
        if not path or path.startswith(_SKIP_PREFIXES):
            continue
        methods = getattr(route, "methods", None) or set()
        endpoint = getattr(route, "endpoint", None)
        doc = (getattr(endpoint, "__doc__", "") or "").strip().split("\n")[0][:160]
        # Identity, not name. The tool name is only filled in when the bus can
        # genuinely dispatch to this exact function.
        tool = handlers.get(id(endpoint), "")

        for method in sorted(m for m in methods if m not in {"HEAD", "OPTIONS"}):
            if (method, path) in seen:
                continue
            seen.add((method, path))
            mode = "write" if method in _WRITE_METHODS else "read"
            entries.append(
                AppCapability(
                    method=method,
                    path=path,
                    mode=mode,
                    area=_area_of(path),
                    summary=doc,
                    auth=_auth_of(route),
                    tool=tool,
                    # The whole point: a write is unreachable unless the bus can
                    # dispatch it. Reads are described, not invoked, so they are
                    # not marked invokable either — this field means "the AI may
                    # call this through the tool bus", and nothing does yet.
                    invokable=mode == "write" and bool(tool),
                )
            )

    entries.sort(key=lambda e: (e.area, e.path, e.method))
    return AppSurface(entries=entries)


__all__ = ["AppCapability", "AppSurface", "describe_app"]
