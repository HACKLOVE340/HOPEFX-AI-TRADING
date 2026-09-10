# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Every /ws route reaches the endpoint it names.

Hoisting a helper out of an endpoint puts a `def` between the decorator and the
function it was meant to decorate. Python does not complain: the decorator
happily registers the helper, the endpoint it was written for is never
registered at all, and the module still imports, still lints, still type-checks.

That happened here — `@router.websocket("/ws/nuclear")` landed on
`_get_nuclear_state`, a synchronous zero-argument helper, so the kill-switch
dashboard feed pointed at a function that cannot accept a socket. Nothing in
the suite noticed, because nothing asserted the wiring.

This is the F176 shape: a control that exists and never runs. The route table
is the wiring, so the wiring is what gets asserted.
"""

from __future__ import annotations

import inspect

import pytest
from starlette.routing import WebSocketRoute

pytestmark = [pytest.mark.unit]


def _ws_routes():
    """WebSocket routes only.

    Selected by route *type*, not by path prefix: `/ws/live/stats` is an
    ordinary HTTP GET that happens to sit under the same prefix, and a
    prefix filter reports it as a broken socket endpoint.
    """
    from api.ws_live import router

    return [r for r in router.routes if isinstance(r, WebSocketRoute)]


class TestEveryWebSocketRouteIsUsable:
    def test_there_are_websocket_routes_at_all(self):
        assert _ws_routes(), "harness is dead if this module registers nothing"

    @pytest.mark.parametrize("path", [r.path for r in _ws_routes()])
    def test_the_endpoint_is_a_coroutine_taking_a_websocket(self, path):
        route = next(r for r in _ws_routes() if r.path == path)
        fn = route.endpoint

        assert inspect.iscoroutinefunction(fn), f"{path} -> {fn.__name__} is not async; Starlette cannot await it"
        params = list(inspect.signature(fn).parameters)
        assert params, f"{path} -> {fn.__name__} takes no arguments, so it cannot receive the socket"

    def test_the_nuclear_feed_reaches_the_nuclear_endpoint(self):
        """Named explicitly: this is the route the regression silently unbound."""
        route = next(r for r in _ws_routes() if r.path == "/ws/nuclear")
        assert route.endpoint.__name__ == "ws_nuclear"

    def test_no_helper_is_registered_as_an_endpoint(self):
        """A private `_`-prefixed name in the route table means a stray decorator."""
        stray = [(r.path, r.endpoint.__name__) for r in _ws_routes() if r.endpoint.__name__.startswith("_")]
        assert stray == [], f"private helpers wired as endpoints: {stray}"
