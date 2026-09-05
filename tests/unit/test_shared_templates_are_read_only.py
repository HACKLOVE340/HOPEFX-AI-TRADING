# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_shared_templates_are_read_only.py
=================================================
Any trader could delete every other trader's research templates.

`research/__init__.py` and `nocode/router.py` both gate ownership through a
single predicate that exempts shared built-ins:

    def _visible_notebook(nb, user_id):
        return nb.is_template or getattr(nb, "user_id", None) in (None, user_id)

    def _visible_to(strategy, user_id):
        owner = getattr(strategy, "user_id", None)
        return owner is None or owner == user_id

That is the right rule for *reading* — templates are meant to be browsable by
everyone. But the same predicate gates the mutating routes, and the templates
live in the **shared** `engine.notebooks` / `builder.strategies` dictionaries
that every request handler reads from. So `DELETE /api/research/notebooks/{id}`
on a built-in succeeded for any authenticated trader and removed it for the
entire deployment. `POST .../cells` and `POST .../execute` likewise wrote into
an object every other user was about to read, and `nocode`'s `PUT`/`DELETE`
mutated the very objects `builder.templates` hands out to the next caller.

Neither is a supported flow. Templates are browsed through
`GET /api/research/templates` and `GET /api/nocode/templates`, and the way to
work from one is `create_from_template`, which copies it under the caller's own
`user_id`. Nothing in either frontend edits a template in place.

So reading keeps the exemption and mutating does not: a route that changes
state requires real ownership, and a built-in has no owner, so nobody owns it.
The 404 (rather than 403) is preserved — it is the existing choice throughout
this codebase, so a response cannot be used to enumerate ids.
"""

from __future__ import annotations

import inspect

import pytest

pytestmark = pytest.mark.unit


class TestResearchNotebooks:
    def test_a_read_only_predicate_still_exempts_templates(self):
        import research

        src = inspect.getsource(research.create_research_router)
        assert "_readable_notebook" in src, "reading a shared template must stay allowed; only mutation is restricted"

    def test_the_mutation_gate_does_not_exempt_templates(self):
        import research

        src = inspect.getsource(research.create_research_router)
        owned = src.split("def _owned_notebook")[1].split("def ")[0]

        assert "is_template" not in owned, (
            "_owned_notebook gates delete, add_cell and execute; exempting templates "
            "there lets any trader mutate or delete a notebook shared with everyone"
        )

    def test_a_template_is_not_owned_by_a_caller(self):
        from research import ResearchNotebookEngine, create_research_router

        engine = ResearchNotebookEngine()
        router = create_research_router(engine)
        gate = _closure(router, "_owned_notebook")
        readable = _closure(router, "_readable_notebook")

        template_id = next(nb_id for nb_id, nb in engine.notebooks.items() if nb.is_template)

        assert readable(engine.notebooks[template_id], "trader-1") is True, (
            "browsing a shared template must keep working"
        )
        with pytest.raises(Exception) as excinfo:
            gate(template_id, "trader-1")
        assert getattr(excinfo.value, "status_code", None) == 404

    def test_a_caller_still_owns_their_own_notebook(self):
        from research import ResearchNotebookEngine, create_research_router

        engine = ResearchNotebookEngine()
        router = create_research_router(engine)
        gate = _closure(router, "_owned_notebook")

        nb = engine.create_notebook(title="Mine", description="", author="trader-1")
        nb.user_id = "trader-1"

        assert gate(nb.notebook_id, "trader-1") is nb

    def test_another_trader_cannot_reach_it(self):
        from research import ResearchNotebookEngine, create_research_router

        engine = ResearchNotebookEngine()
        router = create_research_router(engine)
        gate = _closure(router, "_owned_notebook")

        nb = engine.create_notebook(title="Mine", description="", author="trader-1")
        nb.user_id = "trader-1"

        with pytest.raises(Exception) as excinfo:
            gate(nb.notebook_id, "trader-2")
        assert getattr(excinfo.value, "status_code", None) == 404


class TestNocodeStrategies:
    def test_the_mutation_gate_does_not_exempt_ownerless_builtins(self):
        import nocode.router as mod

        src = inspect.getsource(mod.create_nocode_router)
        owned = src.split("def _owned_strategy")[1].split("def ")[0]

        assert "_visible_to" not in owned, (
            "_owned_strategy gates PUT and DELETE; reusing the read predicate lets any "
            "trader mutate the built-in templates create_from_template hands out"
        )

    def test_a_read_predicate_still_exists_for_listing(self):
        import nocode.router as mod

        src = inspect.getsource(mod.create_nocode_router)
        assert "_visible_to" in src, "listing must still show shared templates"


def _closure(router, name):
    """Pull a nested function out of the router factory's closure."""
    for route in router.routes:
        fn = getattr(route, "endpoint", None)
        if fn is None or fn.__closure__ is None:
            continue
        for cell_name, cell in zip(fn.__code__.co_freevars, fn.__closure__, strict=False):
            if cell_name == name:
                return cell.cell_contents
    raise AssertionError(f"{name} not found in any route closure")
