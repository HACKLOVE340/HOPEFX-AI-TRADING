# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_api_endpoint_doc_is_generated.py
=================================================
Regression tests for finding S-33: ``docs/API_ENDPOINTS.md`` had drifted so far
from the routers that a third of it was fiction.

Measured against the fully registered app, **148 of its 440 rows** named a
(method, path) pair with no route behind it. The mistakes were mechanical,
which is the tell that a human had been maintaining a generated file by hand:

  * the prefix was built from the *module* name instead of the router's real
    one — ``/api/two-factor/setup`` for ``/api/2fa/setup``,
    ``/api/community-chat/rooms`` for ``/api/chat/rooms``;
  * that same guess was prepended to routes whose paths were already absolute,
    producing ``/api/advanced-trading/api/indicators`` and
    ``/api/settings-extended/api/settings/trading``;
  * routes that had moved or been deleted were never removed.

Meanwhile ``scripts/api_documentation_generator.py`` — the file named for
exactly this job — contained five comment lines and
``# ... code implementation ...``. It is implemented now, and this test asserts
the committed doc is what it produces, so the two cannot drift again.

The doc is deliberately generated under **default** feature flags with the
``/api/v1/*`` alias layer omitted; both choices are stated in the generated
header.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC = _REPO_ROOT / "docs" / "API_ENDPOINTS.md"

if str(_REPO_ROOT) not in sys.path:  # pragma: no cover — import bootstrap
    sys.path.insert(0, str(_REPO_ROOT))

_ROW = re.compile(r"^\|\s*`(GET|POST|PUT|PATCH|DELETE)`\s*\|\s*`([^`]+)`\s*\|\s*(JWT|None)\s*\|")


def _generator():
    from scripts import api_documentation_generator

    return api_documentation_generator


def _documented_rows() -> list[tuple[str, str, str]]:
    rows = []
    for line in _DOC.read_text(encoding="utf-8").splitlines():
        match = _ROW.match(line)
        if match:
            rows.append((match.group(1), match.group(2), match.group(3)))
    return rows


@pytest.mark.unit
class TestTheDocMatchesTheRouters:
    def test_the_committed_file_is_what_the_generator_produces(self):
        assert _DOC.read_text(encoding="utf-8") == _generator().render(), (
            "docs/API_ENDPOINTS.md is out of date — run "
            "`python scripts/api_documentation_generator.py`. It is generated "
            "from the registered routers; hand-editing it is how 148 fictional "
            "rows accumulated (S-33)."
        )

    def test_check_mode_agrees(self):
        assert _generator().main(["--check"]) == 0

    def test_every_documented_path_actually_exists(self):
        """The property that matters, asserted independently of the generator.

        If the generator itself started emitting nonsense, the equality test
        above would happily pass on it. This one goes back to the app.
        """
        from core.router_registry import iter_api_routes

        app = _generator()._build_app()
        real = {(method, route.path) for route in iter_api_routes(app.routes) for method in route.methods}

        missing = [f"{method} {path}" for method, path, _ in _documented_rows() if (method, path) not in real]

        assert not missing, f"documented endpoints with no route: {missing[:20]} ({len(missing)} total)"


@pytest.mark.unit
class TestTheTableIsNotEmptyOrTrivial:
    """So a broken generator cannot make the tests above pass by writing nothing."""

    def test_it_lists_a_realistic_number_of_endpoints(self):
        rows = _documented_rows()
        assert len(rows) > 800, f"only {len(rows)} rows parsed — the format or the generator changed"

    def test_the_paths_that_must_be_there_are(self):
        paths = {path for _, path, _ in _documented_rows()}

        for path in (
            "/api/auth/login",
            "/api/trading/orders",
            "/api/monetization/license/validate",
            "/api/indicators",
            "/api/custom-indicators",
        ):
            assert path in paths, f"{path} is missing from the endpoint table"

    def test_no_v1_alias_rows(self):
        """They mirror every path above and would double the table."""
        assert not [path for _, path, _ in _documented_rows() if path.startswith("/api/v1/")]


@pytest.mark.unit
class TestTheAuthColumnDoesNotUnderstate:
    """S-31's lesson: a doc that under-states auth invites removing the gate."""

    def test_a_known_gated_route_is_marked_jwt(self):
        auth = {path: value for _, path, value in _documented_rows()}

        for path in (
            "/api/monetization/pricing",  # was documented as public in docs/API.md
            "/api/auth/me",  # resolved through auth/router.py's own helper
            "/api/security/fixes",  # admin-gated
            "/api/orders/advanced/oco",  # router-level require_role
        ):
            assert auth.get(path) == "JWT", f"{path} is documented as {auth.get(path)!r}"

    def test_the_open_routes_are_ones_that_should_be(self):
        """Pins the deliberate exceptions so a new `None` row gets noticed.

        The first version of this list carried `"/"` for the root route. Since
        the check was `startswith(tuple)`, that prefix matched every path in
        the repo and the assertion could not fail — it passed while
        `/api/stream/*` sat unlisted. Exact paths and prefixes are kept apart
        now for exactly that reason.
        """
        open_paths = {path for _, path, value in _documented_rows() if value == "None"}

        allowed_exact = {
            "/api/nuclear/snapshot",  # aggregate sentiment score, no user data
            "/api/performance/public",  # the published track record
            "/api/copy-trading/masters",  # public master-trader directory
            "/api/billing/plans",
            "/api/billing/stripe/config",  # publishable key only
            "/api/payments/webhook",  # HMAC-SHA256 over the raw body
            "/api/webhooks/tradingview",  # HMAC-SHA256, X-TV-Signature
            "/api/backtesting/replay/regimes",  # static list of stress scenarios
            "/api/custom-indicators/builtin",  # standard indicator definitions
            "/api/sentiment/latest",
            "/api/status",
            "/mobile/health",
            "/ws/live/stats",  # connection counts
        }

        # Every other unauthenticated route must be explainable as one of these.
        allowed_prefixes = (
            # Unauthenticated by necessity: this is where a caller gets a token.
            "/api/auth/",
            "/mobile/api/v2/auth/",
            # Probes and the public status page.
            "/api/health/",
            "/api/status/",
            # Market data — aggregate microstructure, no per-user content. Same
            # class as the /ws/public socket.
            "/api/dom/",
            "/api/orderflow/",
            "/api/timesales/",
            "/api/stream/",
            "/api/dashboard/",
            "/api/macro/",
            "/api/news/",
            "/api/public/",
            # Public-facing product surface: pricing, the trader directory, the
            # signal feed and the transparency reports are all meant to be
            # readable before signup.
            "/api/pricing/",
            "/api/profiles",
            "/api/leaderboard",
            "/api/feed",
            "/api/transparency/",
            "/api/billing/payments/",  # provider redirect status
            "/api/backtesting/shared/",  # opt-in share links
            # Inbound webhooks — authenticated by signature, not by a token the
            # sender could not present anyway.
            "/api/billing/webhook/",
            "/api/monetization/webhook/",
            "/kyc/webhooks/",
        )

        unexpected = sorted(p for p in open_paths if p not in allowed_exact and not p.startswith(allowed_prefixes))

        assert not unexpected, (
            "these endpoints have no auth gate this check can find, and are not "
            f"on the deliberate-exception list: {unexpected}. Either add a gate "
            "or, if it is genuinely public, add it above with a reason."
        )

    def test_the_exception_list_is_not_a_rubber_stamp(self):
        """A prefix broad enough to match everything would void the test above."""
        source = Path(__file__).read_text(encoding="utf-8")
        block = source.split("allowed_prefixes = (", 1)[1].split(")", 1)[0]
        entries = re.findall(r'"([^"]+)"', block)

        assert entries, "the prefix list could not be parsed — this guard is not guarding"
        for entry in entries:
            assert entry not in ("/", "/api", "/api/", "/mobile", "/mobile/"), (
                f"{entry!r} is broad enough to match nearly every path, which is how "
                "the first version of this test passed while /api/stream/* sat unlisted"
            )
