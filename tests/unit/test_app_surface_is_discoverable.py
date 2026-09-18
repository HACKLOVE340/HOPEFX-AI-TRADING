# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""What the platform can do, described to the AI by the platform itself.

The architectural question this answers: is the AI a feature inside the app, or
is the app a set of capabilities the AI can see? §4 and §31 want the second —
"the AI understands the situation and constructs the environment required" — and
the difference is not cosmetic. An AI that only knows the endpoints somebody
remembered to wire is permanently one commit behind its own platform, and the
gap is invisible: nothing fails, the AI is simply ignorant of a feature that
shipped last week.

So the catalogue is DERIVED from the running application. 65 routers are
mounted; a hand-maintained list of them would be wrong within a day.

## The rule that matters more than the feature

**Discovery is not capability.** Knowing that `POST /api/trading/order` exists
must not mean the AI can call it. Execution stays behind `ai/tools/bus.py` and
its fail-closed permission gate — the catalogue reports what the platform can
do, never what the AI may do, and every write is marked unreachable unless a
tool was explicitly registered for it.

A catalogue that blurred those two would be worse than no catalogue: it would
read as a menu.

These tests fail on the pre-fix tree — `ai.hub.app_surface` does not exist.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def catalogue():
    from ai.hub.app_surface import describe_app

    return describe_app()


# ── it is derived, not declared ───────────────────────────────────────────────


def test_it_finds_the_real_routes_of_the_running_app(catalogue):
    """A hand-maintained list of 65 routers' endpoints would be wrong within a
    day. This reads `app.routes`."""
    assert len(catalogue.entries) > 100, f"only {len(catalogue.entries)} routes; the app has far more"


def test_it_covers_the_areas_an_operator_would_name(catalogue):
    paths = " ".join(e.path for e in catalogue.entries)
    for area in ("/api/trading", "/api/ai-core", "/api/risk", "/api/safe-platform"):
        assert area in paths, f"the catalogue cannot see {area}"


def test_it_cannot_go_stale_because_nothing_is_typed_by_hand(catalogue):
    """The registry in `capabilities.py` is a deliberate declaration of intent.
    This is the opposite: a measurement of what exists. If someone adds a router
    tomorrow it appears here without anybody editing a list."""
    import inspect

    from ai.hub import app_surface

    src = inspect.getsource(app_surface)
    assert "app.routes" in src or "routes" in src


# ── read and write are not the same thing ─────────────────────────────────────


def test_every_entry_says_whether_it_reads_or_writes(catalogue):
    for entry in catalogue.entries:
        assert entry.mode in {"read", "write"}, f"{entry.path} is neither"


def test_a_get_is_a_read_and_a_post_is_a_write(catalogue):
    by_path = {(e.method, e.path): e for e in catalogue.entries}
    reads = [e for (m, _), e in by_path.items() if m == "GET"]
    writes = [e for (m, _), e in by_path.items() if m in {"POST", "PUT", "PATCH", "DELETE"}]
    assert reads and writes
    assert all(e.mode == "read" for e in reads)
    assert all(e.mode == "write" for e in writes)


# ── discovery is not capability ───────────────────────────────────────────────


def test_no_write_is_marked_invokable_unless_a_tool_was_registered(catalogue):
    """The one that matters. Seeing `POST /api/trading/order` must not mean the
    AI can place an order.

    Compared against `implemented_actions()` — what `build_tool_bus()` actually
    registers — rather than against an empty set. An assertion whose right-hand
    side is always empty passes whatever the code does.
    """
    from ai.departments import implemented_actions

    registered = {action.name for action in implemented_actions()}
    assert registered, "no tools are registered at all; this assertion would be vacuous"

    wrongly_open = [e.path for e in catalogue.entries if e.mode == "write" and e.invokable and e.tool not in registered]
    assert not wrongly_open, f"writes marked invokable with no registered tool: {wrongly_open[:5]}"


def test_invokable_turns_on_when_a_bus_handler_really_is_the_endpoint(catalogue):
    """The inverse, so the rule above is not merely true-because-empty.

    Every write in the real catalogue is unreachable, which is correct and also
    indistinguishable from a field that is hard-wired to False. This builds a
    small app whose route handler IS a registered bus handler and checks the
    flag flips — so the mechanism is proven to work in both directions before
    anyone relies on it saying no.
    """
    from fastapi import FastAPI

    from ai.departments import implemented_actions
    from ai.hub.app_surface import describe_app

    action = next(iter(implemented_actions()))

    app = FastAPI()
    # Registered as the endpoint itself — identity, which is what the catalogue
    # matches on. A same-named different function would (correctly) not count.
    app.add_api_route("/api/probe/thing", action.handler, methods=["POST"])

    entry = next(e for e in describe_app(app).entries if e.path == "/api/probe/thing")
    assert entry.mode == "write"
    assert entry.tool == action.name
    assert entry.invokable is True, "a genuinely dispatchable write was still marked unreachable"


def test_the_dangerous_endpoints_are_visible_and_not_invokable(catalogue):
    """It should KNOW the platform can place an order — that is the point of a
    catalogue — while being unable to do it from here."""
    orders = [e for e in catalogue.entries if "order" in e.path and e.mode == "write"]
    assert orders, "the catalogue cannot see order placement at all"
    assert all(not e.invokable for e in orders), "an order endpoint is marked invokable"


def test_the_summary_separates_what_it_can_see_from_what_it_can_do(catalogue):
    """Two numbers, never one. Conflating them is how a map becomes a menu."""
    s = catalogue.summary()
    assert s["visible"] > 100
    assert s["invokable"] < s["visible"]
    assert "reads" in s and "writes" in s


# ── it must not leak ──────────────────────────────────────────────────────────


def test_it_carries_no_credential_values(catalogue):
    """A description of the platform is not a copy of its secrets.

    The check is for credential *values*, not for the word. This first read
    `"password" not in blob` and failed on `/api/admin/users/{id}/reset-password`
    — a route path, and one the AI needs to know about. Banning the vocabulary
    would have banned the capability; what must never appear is an assigned
    value or a bearer token.
    """
    import re

    blob = repr([(e.path, e.summary, e.auth) for e in catalogue.entries]).lower()
    patterns = [
        r"(password|api[_-]?key|secret|token)\s*[=:]\s*['\"]?[\w.\-]{6,}",
        r"bearer\s+[\w.\-]{12,}",
        r"\b(sk|pk|ghp|xox[abp])[-_][\w]{16,}",
    ]
    for pattern in patterns:
        hit = re.search(pattern, blob)
        assert hit is None, f"the catalogue contains a credential value: {hit.group(0)!r}"


def test_it_carries_no_request_bodies_or_parameter_schemas(catalogue):
    """Tested by absence, because the leak would arrive as a new field.

    A catalogue that quoted request models would eventually quote one with a
    credential field name and a sample value in its description. The defence is
    that there is nowhere to put one: `AppCapability` has exactly these fields,
    and adding a `request_model` or `schema` fails here before it can ship.
    """
    import dataclasses

    from ai.hub.app_surface import AppCapability

    fields = {f.name for f in dataclasses.fields(AppCapability)}
    assert fields == {"method", "path", "mode", "area", "summary", "auth", "tool", "invokable"}, (
        f"AppCapability grew or lost a field: {sorted(fields)}"
    )


def test_it_records_which_role_each_route_needs(catalogue):
    """§25 capability-based permissions. An AI that does not know a route is
    superadmin-only will propose it to a trader and be refused, repeatedly."""
    assert any(e.auth for e in catalogue.entries), "no route reports an auth requirement"


# ── it has to be readable, or it is another control nobody runs ───────────────


@pytest.mark.asyncio
async def test_an_endpoint_exposes_it():
    from api.ai_core import ai_core_app_surface
    from api.auth import TokenPayload

    body = await ai_core_app_surface(TokenPayload(sub="owner", role="superadmin"))
    assert body["visible"] > 100
    assert body["invokable"] < body["visible"]
    assert isinstance(body["areas"], list) and body["areas"]


# ── it has to be searchable, or 2,200 rows are the same as none ───────────────


def test_search_does_not_return_a_third_of_the_platform(catalogue):
    """The first scoring pass counted any word of three letters or more, so
    "check the current drawdown against risk limits" matched 850 of 2,234
    routes — "current" alone appears in a third of the docstrings here. A result
    set that large is arbitrary, which is the same defect this repository
    shipped once in `Scene.resolve`, where "nothing like this" matched a panel
    titled "gold price THIS session"."""
    hits = catalogue.search("check the current drawdown against risk limits")
    assert 0 < len(hits) <= 12, f"{len(hits)} hits"
    assert any("/api/risk" in e.path for e in hits), "the risk routes are not in the top results"


def test_search_returns_nothing_for_a_phrase_made_only_of_stopwords(catalogue):
    """Better than returning everything, which is what scoring 'the current
    status of all the data' against every docstring would do."""
    assert catalogue.search("what is the current status of all the data") == []


def test_search_is_deterministic_rather_than_registration_ordered(catalogue):
    """A catalogue that answers the same question differently depending on which
    router happened to mount first is not something to reason from.

    Asserted by shuffling, not by calling twice: calling twice passes on any
    implementation that is merely repeatable, including one whose tie-break is
    "whatever order the routers mounted in". Reversing the entry list changes
    that order and must change nothing about the answer.
    """
    from ai.hub.app_surface import AppSurface

    forward = [(e.method, e.path) for e in catalogue.search("risk drawdown limits")]
    reversed_catalogue = AppSurface(entries=list(reversed(catalogue.entries)))
    backward = [(e.method, e.path) for e in reversed_catalogue.search("risk drawdown limits")]

    assert forward, "no hits at all; this assertion would be vacuous"
    assert forward == backward, "search results depend on the order routers were registered in"


def test_a_word_in_the_path_outranks_the_same_word_in_prose(catalogue):
    """`/api/risk/limits` is a much stronger signal than a docstring that
    happens to mention risk in passing."""
    hits = catalogue.search("risk")
    assert hits, "no hits for the single most common area in this platform"
    assert all("risk" in e.path.lower() or "risk" in e.area.lower() for e in hits[:5])


def test_the_prompt_form_says_a_route_is_not_permission(catalogue):
    """The whole module's rule, restated where a model will actually read it."""
    text = catalogue.as_prompt("drawdown and risk limits")
    assert "cannot call these" in text
    assert "permitted actions" in text


def test_the_prompt_form_says_so_when_nothing_matches(catalogue):
    """Silence and 'nothing matched' are different facts; a model given an empty
    string will invent the difference."""
    assert catalogue.as_prompt("zzzqqxx") == "No platform capability matches this goal."
