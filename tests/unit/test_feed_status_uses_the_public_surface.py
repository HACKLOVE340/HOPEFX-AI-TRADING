# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The feed-status endpoint reaches `data_layer` through its public surface.

`data_layer`'s public surface is exactly three names — `orchestrator`,
`tick_store`, `feeds.*` — documented in CLAUDE.md and enforced by
`scripts/ci/gate_g_import_discipline.py`. Everything else is an internal, and
an API module importing one couples the HTTP layer to a file the boundary was
drawn to let move.

`api/data_layer.py` did exactly that: `from data_layer.outage import
get_supervisor`, added in ff765d2. The gate has reported it as a NEW violation
ever since, which is the gate working; nothing had acted on it.

The fix is not to widen the surface — that would retire the rule to avoid
following it. It is to expose feed-outage status *on* the surface, where the
orchestrator already owns the relationship: it is the thing that feeds the
supervisor its observations.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.unit]

PUBLIC = {"orchestrator", "tick_store", "feeds"}


def _data_layer_imports(path: str) -> list[str]:
    tree = ast.parse(pathlib.Path(path).read_text())
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").startswith("data_layer"):
            found.append(node.module)
        elif isinstance(node, ast.Import):
            found.extend(a.name for a in node.names if a.name.startswith("data_layer"))
    return found


class TestTheApiLayerStaysOnTheSurface:
    def test_the_harness_sees_the_imports_it_is_judging(self):
        """Liveness: an empty list would make the assertion below vacuous."""
        assert _data_layer_imports("api/data_layer.py"), "no data_layer imports found — wrong file or a parse failure"

    def test_no_data_layer_internal_is_imported(self):
        offenders = [
            m for m in _data_layer_imports("api/data_layer.py") if m.split(".")[1:2] and m.split(".")[1] not in PUBLIC
        ]
        assert offenders == [], f"api/data_layer.py reaches into data_layer internals: {offenders}"


class TestTheNameOrchestratorIsShadowed:
    """`data_layer/__init__.py` binds the singleton over the submodule name.

    So `from data_layer import orchestrator` yields a
    `MarketDataOrchestrator` **instance**, not the module — and because
    `import a.b as c` resolves `b` as an attribute of `a` before consulting
    `sys.modules`, `import data_layer.orchestrator as m` gives the instance
    too. Only `from data_layer.orchestrator import <name>` reaches the module.

    This cost time here and the identical shape cost time in `support/`
    earlier. It is pinned rather than fixed: unbinding the singleton is an API
    change for 86 production importers, which is not this change's business.
    """

    def test_the_package_attribute_is_the_instance_not_the_module(self):
        from data_layer import orchestrator as attr
        from data_layer.orchestrator import MarketDataOrchestrator

        assert isinstance(attr, MarketDataOrchestrator), (
            "the shadowing is gone — good, but update the note above and the callers that rely on it"
        )

    def test_the_module_itself_is_still_reachable(self):
        import sys

        assert "data_layer.orchestrator" in sys.modules


class TestTheOrchestratorExposesFeedOutageStatus:
    def test_the_public_surface_offers_it(self):
        import sys

        import data_layer.orchestrator  # noqa: F401 — populates sys.modules

        module = sys.modules["data_layer.orchestrator"]
        assert hasattr(module, "get_feed_outage_status")

    def test_it_returns_the_supervisor_state(self, monkeypatch):
        import types

        from data_layer import outage
        from data_layer.orchestrator import get_feed_outage_status

        sentinel = {"state": "degraded", "age_s": 42.0, "deferred": 0}
        monkeypatch.setattr(outage, "get_supervisor", lambda: types.SimpleNamespace(as_dict=lambda: sentinel))

        assert get_feed_outage_status() == sentinel

    def test_it_reports_the_three_documented_states_for_real(self):
        """Against the real supervisor, not a stub — the accessor must work."""
        from data_layer.orchestrator import get_feed_outage_status

        got = get_feed_outage_status()

        assert isinstance(got, dict)
        assert got["health"]["state"] in {"healthy", "degraded", "outage"}, got

    def test_a_supervisor_failure_is_not_swallowed(self, monkeypatch):
        """The HTTP caller turns this into a 503. An accessor that returned a
        cheerful empty dict would make that impossible."""
        from data_layer import outage
        from data_layer.orchestrator import get_feed_outage_status

        def _boom():
            raise RuntimeError("supervisor unavailable")

        monkeypatch.setattr(outage, "get_supervisor", _boom)

        with pytest.raises(RuntimeError):
            get_feed_outage_status()


class TestTheGateAgrees:
    """The gate is the enforcement; this test is here so a regression names the
    reason rather than surfacing as an opaque CI failure."""

    def test_no_new_import_discipline_violations(self):
        result = subprocess.run(
            [sys.executable, "scripts/ci/gate_g_import_discipline.py"],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,  # the return code IS the assertion
        )
        assert result.returncode == 0, result.stdout[-2000:]
