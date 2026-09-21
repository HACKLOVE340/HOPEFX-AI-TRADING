# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_ws_token_not_in_query_string.py
===============================================
Every WebSocket in this product authenticated by putting the access token in
the URL.

    frontend/src/pages/NotificationsPage.tsx:86
    frontend/src/pages/SocialFeed.tsx:76
    frontend/src/pages/ChatPage.tsx:115
    frontend/src/pages/AuditLog.tsx:192
    frontend/src/lib/utils.ts:345   (the documented example other code copies)

all build `${getWsBase()}/ws/...?token=${token}`, and three backend handlers
read it back — `api/ws_live.py` twice and `api/gateway.py::websocket_stream`,
where the query parameter is the *only* accepted credential.

A URL is not a private channel. The query string is written to nginx and load
balancer access logs, kept in browser history, forwarded in `Referer` on
subsequent navigations, and attached to APM and error-reporting spans — this
repository's own Sentry `before_send` did not scrub `request.query_string`
until the previous commit, so live access tokens were reaching a third party
in plain text. Anyone with log read access has a replayable credential.

Headers do not have that problem, but browsers give `new WebSocket()` no way
to set one. The mechanism they *do* give is the subprotocol list, which the
handshake carries in `Sec-WebSocket-Protocol` — a header, and therefore absent
from access logs and `Referer`.

So the token moves to the subprotocol:

    new WebSocket(url, ["hopefx.auth.bearer", token])

The server must echo the accepted subprotocol back on `accept()` or the
browser closes the connection immediately, which is the part that is easy to
get wrong and silent when you do.

The query parameter keeps working. Non-browser clients and scripts already use
it, and breaking them to fix a logging problem would be its own outage; it is
now a deprecated fallback that logs a warning naming the client, and it can be
switched off entirely with `WS_ALLOW_QUERY_TOKEN=false` once a deployment's
clients have moved.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

_SUBPROTOCOL = "hopefx.auth.bearer"


def _ws(headers: dict | None = None, query: dict | None = None):
    """Minimal stand-in with the two surfaces the extractor reads."""
    return SimpleNamespace(
        headers=headers or {},
        query_params=query or {},
        client=SimpleNamespace(host="203.0.113.10"),
    )


class TestTheExtractor:
    def test_it_exists(self):
        from api.ws_live import ws_auth_token

        assert callable(ws_auth_token)

    def test_it_reads_the_token_from_the_subprotocol_header(self):
        from api.ws_live import ws_auth_token

        ws = _ws(headers={"sec-websocket-protocol": f"{_SUBPROTOCOL}, jwt-value-here"})

        assert ws_auth_token(ws) == "jwt-value-here"

    def test_it_tolerates_the_header_without_a_space_after_the_comma(self):
        from api.ws_live import ws_auth_token

        assert ws_auth_token(_ws(headers={"sec-websocket-protocol": f"{_SUBPROTOCOL},jwt-value-here"})) == (
            "jwt-value-here"
        )

    def test_an_unrelated_subprotocol_is_not_treated_as_a_token(self):
        from api.ws_live import ws_auth_token

        assert ws_auth_token(_ws(headers={"sec-websocket-protocol": "graphql-ws"})) is None

    def test_it_falls_back_to_the_query_parameter(self):
        """Existing clients must keep working."""
        from api.ws_live import ws_auth_token

        assert ws_auth_token(_ws(query={"token": "legacy-jwt"})) == "legacy-jwt"

    def test_the_subprotocol_wins_over_the_query_parameter(self):
        from api.ws_live import ws_auth_token

        ws = _ws(headers={"sec-websocket-protocol": f"{_SUBPROTOCOL}, header-jwt"}, query={"token": "url-jwt"})

        assert ws_auth_token(ws) == "header-jwt"

    def test_no_credential_at_all_returns_none(self):
        from api.ws_live import ws_auth_token

        assert ws_auth_token(_ws()) is None

    def test_the_query_parameter_can_be_switched_off(self, monkeypatch):
        """Once a deployment's clients have moved, the leak can be closed."""
        from api.ws_live import ws_auth_token

        monkeypatch.setenv("WS_ALLOW_QUERY_TOKEN", "false")

        assert ws_auth_token(_ws(query={"token": "legacy-jwt"})) is None

    def test_turning_it_off_does_not_affect_the_subprotocol(self, monkeypatch):
        from api.ws_live import ws_auth_token

        monkeypatch.setenv("WS_ALLOW_QUERY_TOKEN", "false")
        ws = _ws(headers={"sec-websocket-protocol": f"{_SUBPROTOCOL}, header-jwt"})

        assert ws_auth_token(ws) == "header-jwt"

    def test_a_malformed_header_does_not_raise(self):
        """This runs before auth, so anything reachable is attacker-controlled."""
        from api.ws_live import ws_auth_token

        for value in ("", ",", f"{_SUBPROTOCOL},", f"{_SUBPROTOCOL}, , ", "a, b, c, d"):
            ws_auth_token(_ws(headers={"sec-websocket-protocol": value}))


class TestTheAcceptedSubprotocolIsEchoed:
    def test_the_helper_reports_what_to_echo(self):
        """A browser closes the socket if the server does not name the protocol back."""
        from api.ws_live import ws_accept_subprotocol

        ws = _ws(headers={"sec-websocket-protocol": f"{_SUBPROTOCOL}, jwt-value"})

        assert ws_accept_subprotocol(ws) == _SUBPROTOCOL

    def test_nothing_is_echoed_when_the_client_offered_nothing(self):
        from api.ws_live import ws_accept_subprotocol

        assert ws_accept_subprotocol(_ws()) is None

    def test_nothing_is_echoed_for_an_unrelated_subprotocol(self):
        from api.ws_live import ws_accept_subprotocol

        assert ws_accept_subprotocol(_ws(headers={"sec-websocket-protocol": "graphql-ws"})) is None


class TestTheHandlersUseIt:
    @pytest.mark.parametrize(
        "path",
        [
            "api/ws_live.py",
            "api/gateway.py",
            # community_chat and social_feed were missed on the first pass: the
            # frontend pages were moved onto the subprotocol while their handlers
            # still read only the query string, so chat and the social feed
            # rejected every browser client. The original sweep grepped two named
            # files instead of the whole api/ package.
            "api/community_chat.py",
            "api/social_feed.py",
        ],
    )
    def test_no_handler_reads_the_token_straight_off_the_query_string(self, path):
        """The one permitted read is the deprecated fallback inside ws_auth_token.

        Anywhere else and the subprotocol is bypassed, the deprecation warning
        never fires, and WS_ALLOW_QUERY_TOKEN=false stops closing the leak.
        """
        import ast
        from pathlib import Path

        src = Path(path).read_text()
        tree = ast.parse(src)

        allowed: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "ws_auth_token":
                allowed = set(range(node.lineno, (node.end_lineno or node.lineno) + 1))

        offenders = [
            i for i, line in enumerate(src.splitlines(), 1) if 'query_params.get("token"' in line and i not in allowed
        ]
        assert not offenders, (
            f"{path} reads the token directly from the URL at line(s) {offenders}; it must "
            f"go through ws_auth_token() so the subprotocol is preferred and the "
            f"deprecated query-string path is logged and switchable"
        )

    def test_every_accept_that_authenticates_echoes_the_subprotocol(self):
        """Otherwise the browser closes the connection and the fix looks broken."""
        from pathlib import Path

        for path in ("api/ws_live.py", "api/gateway.py"):
            src = Path(path).read_text()
            if "ws_auth_token" in src:
                assert "ws_accept_subprotocol" in src, f"{path} authenticates but never echoes the subprotocol"


class TestNoHandlerWasMissed:
    def test_every_websocket_handler_in_the_api_package_uses_the_extractor(self):
        """The sweep must cover api/, not a hand-listed pair of files.

        Missing one is silent and fail-closed: the page sends the subprotocol,
        the handler looks only at the query string, finds nothing, and closes
        4001. The product breaks and no test notices.
        """
        from pathlib import Path

        offenders = []
        for py in sorted(Path("api").rglob("*.py")):
            src = py.read_text()
            if 'websocket.query_params.get("token"' not in src:
                continue
            if py.name == "ws_live.py":
                continue  # the deprecated fallback lives inside ws_auth_token
            offenders.append(str(py))

        assert not offenders, (
            f"{offenders} read the token from the URL without going through "
            f"ws_auth_token(), so a client using the subprotocol is rejected"
        )


class TestTheFrontendStoppedPuttingItInTheUrl:
    @pytest.mark.parametrize(
        "path",
        [
            "frontend/src/pages/NotificationsPage.tsx",
            "frontend/src/pages/SocialFeed.tsx",
            "frontend/src/pages/ChatPage.tsx",
            "frontend/src/pages/AuditLog.tsx",
        ],
    )
    def test_no_page_builds_a_ws_url_carrying_the_token(self, path):
        from pathlib import Path

        src = Path(path).read_text()
        assert "?token=" not in src, (
            f"{path} still puts the access token in the WebSocket URL, where it reaches "
            f"access logs, browser history and Referer headers"
        )

    def test_the_documented_example_no_longer_teaches_it(self):
        """utils.ts's example is what the next page will be copied from."""
        from pathlib import Path

        src = Path("frontend/src/lib/utils.ts").read_text()
        assert "?token=${token}" not in src

    def test_a_shared_helper_exists_so_call_sites_cannot_drift(self):
        from pathlib import Path

        src = Path("frontend/src/lib/ws.ts").read_text()
        assert "hopefx.auth.bearer" in src
        assert "export function openAuthenticatedWebSocket" in src
