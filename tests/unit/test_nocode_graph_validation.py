# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_nocode_graph_validation.py
==========================================
`POST /api/nocode/validate` always returned its internal-error branch.

    from nocode.state_machine import StateMachineEngine
    engine = StateMachineEngine()
    result = engine.validate_graph(nodes=request.nodes, edges=request.edges)

Neither name exists. `nocode/state_machine.py` defines `StateMachineBuilder`,
`StateMachineDefinition`, `State`, `Transition`, `Condition` and `Action` — a
states-and-transitions builder, not a nodes-and-edges graph validator — and
`validate_graph` appears nowhere in the repository. The import raised
`ImportError` on every request, the `except Exception` caught it, and the
endpoint answered

    {"valid": false, "errors": ["<internal error>"], "warnings": []}

for every input, valid or not. A caller could not tell a broken strategy from a
broken endpoint, and the builder UI had no working validation at all.

The endpoint's docstring states the contract: "valid node types, proper
connections, no cycles in execution flow, and required parameters". That is
what `nocode.graph_validation.validate_graph` now implements.

**The taxonomy moved.** The 22 node types were defined inline inside the
`/node-types` handler. A validator needs the same list, and a second copy would
drift from the first — the failure mode this backlog keeps finding. `NODE_TYPES`
now lives in `nocode/graph_validation.py` and `/node-types` serves it, so the
palette the UI renders and the rules the validator enforces cannot disagree.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _node(node_id: str, node_type: str, **params):
    return {"id": node_id, "type": node_type, "params": params}


class TestTaxonomyIsSharedNotCopied:
    def test_node_types_is_importable_from_the_domain_package(self):
        from nocode.graph_validation import NODE_TYPES

        assert set(NODE_TYPES) == {"indicators", "conditions", "actions", "ml_nodes", "risk"}

    def test_the_endpoint_serves_the_same_object_it_validates_against(self):
        """One source of truth, so the palette and the rules cannot drift."""
        import inspect

        from api.nocode import get_node_types

        source = inspect.getsource(get_node_types)
        assert "NODE_TYPES" in source, "the handler still defines its own copy of the taxonomy"

    def test_every_known_type_id_is_unique_across_categories(self):
        from nocode.graph_validation import NODE_TYPES

        ids = [item["id"] for items in NODE_TYPES.values() for item in items]
        assert len(ids) == len(set(ids))


class TestValidNodeTypes:
    def test_a_known_node_type_passes(self):
        from nocode.graph_validation import validate_graph

        result = validate_graph([_node("n1", "rsi", period=14)], [])
        assert result["valid"] is True, result["errors"]

    def test_an_unknown_node_type_is_rejected(self):
        from nocode.graph_validation import validate_graph

        result = validate_graph([_node("n1", "not_a_real_indicator")], [])
        assert result["valid"] is False
        assert any("not_a_real_indicator" in e for e in result["errors"])

    def test_a_node_without_a_type_is_rejected(self):
        from nocode.graph_validation import validate_graph

        result = validate_graph([{"id": "n1"}], [])
        assert result["valid"] is False

    def test_duplicate_node_ids_are_rejected(self):
        from nocode.graph_validation import validate_graph

        result = validate_graph([_node("n1", "rsi", period=14), _node("n1", "ema", period=20)], [])
        assert result["valid"] is False
        assert any("n1" in e for e in result["errors"])


class TestRequiredParameters:
    def test_a_missing_required_param_is_rejected(self):
        """rsi declares params: ["period"]."""
        from nocode.graph_validation import validate_graph

        result = validate_graph([_node("n1", "rsi")], [])
        assert result["valid"] is False
        assert any("period" in e for e in result["errors"])

    def test_all_declared_params_present_passes(self):
        from nocode.graph_validation import validate_graph

        result = validate_graph([_node("n1", "macd", fast=12, slow=26, signal=9)], [])
        assert result["valid"] is True, result["errors"]

    def test_a_node_type_with_no_params_needs_none(self):
        """crossover declares inputs but no params."""
        from nocode.graph_validation import validate_graph

        result = validate_graph([_node("c1", "crossover")], [])
        assert result["valid"] is True, result["errors"]


class TestConnections:
    def test_an_edge_to_a_missing_node_is_rejected(self):
        from nocode.graph_validation import validate_graph

        result = validate_graph(
            [_node("n1", "rsi", period=14)],
            [{"source": "n1", "target": "ghost"}],
        )
        assert result["valid"] is False
        assert any("ghost" in e for e in result["errors"])

    def test_an_edge_from_a_missing_node_is_rejected(self):
        from nocode.graph_validation import validate_graph

        result = validate_graph(
            [_node("n1", "rsi", period=14)],
            [{"source": "ghost", "target": "n1"}],
        )
        assert result["valid"] is False

    def test_a_well_formed_connection_passes(self):
        from nocode.graph_validation import validate_graph

        result = validate_graph(
            [_node("n1", "rsi", period=14), _node("a1", "buy", lot_size=0.1)],
            [{"source": "n1", "target": "a1"}],
        )
        assert result["valid"] is True, result["errors"]


class TestCycles:
    def test_a_cycle_is_rejected(self):
        from nocode.graph_validation import validate_graph

        result = validate_graph(
            [_node("n1", "rsi", period=14), _node("n2", "ema", period=20), _node("n3", "sma", period=50)],
            [
                {"source": "n1", "target": "n2"},
                {"source": "n2", "target": "n3"},
                {"source": "n3", "target": "n1"},
            ],
        )
        assert result["valid"] is False
        assert any("cycle" in e.lower() for e in result["errors"])

    def test_a_self_loop_is_rejected(self):
        from nocode.graph_validation import validate_graph

        result = validate_graph([_node("n1", "rsi", period=14)], [{"source": "n1", "target": "n1"}])
        assert result["valid"] is False
        assert any("cycle" in e.lower() for e in result["errors"])

    def test_a_diamond_is_not_a_cycle(self):
        """Two paths reconverging is a DAG, not a loop — a naive visited-set check fails this."""
        from nocode.graph_validation import validate_graph

        result = validate_graph(
            [
                _node("src", "rsi", period=14),
                _node("l", "ema", period=20),
                _node("r", "sma", period=50),
                _node("dst", "buy", lot_size=0.1),
            ],
            [
                {"source": "src", "target": "l"},
                {"source": "src", "target": "r"},
                {"source": "l", "target": "dst"},
                {"source": "r", "target": "dst"},
            ],
        )
        assert result["valid"] is True, result["errors"]


class TestResponseShape:
    def test_the_shape_matches_what_the_endpoint_returned_before(self):
        from nocode.graph_validation import validate_graph

        result = validate_graph([], [])
        assert set(result) >= {"valid", "errors", "warnings"}
        assert isinstance(result["errors"], list)
        assert isinstance(result["warnings"], list)

    def test_an_empty_graph_warns_rather_than_erroring(self):
        from nocode.graph_validation import validate_graph

        result = validate_graph([], [])
        assert result["warnings"], "an empty strategy should tell the user something"

    def test_a_graph_with_no_action_node_warns(self):
        """Indicators alone can never place a trade."""
        from nocode.graph_validation import validate_graph

        result = validate_graph([_node("n1", "rsi", period=14)], [])
        assert result["valid"] is True
        assert any("action" in w.lower() for w in result["warnings"])

    def test_validation_never_raises_on_malformed_input(self):
        """The endpoint reports findings; it must not turn bad input into a 500."""
        from nocode.graph_validation import validate_graph

        for nodes, edges in (
            ("not a list", []),
            ([None], []),
            ([{"id": "n1", "type": "rsi", "params": None}], [{"source": None}]),
            ([{"id": 1, "type": "rsi"}], "not a list"),
        ):
            result = validate_graph(nodes, edges)
            assert result["valid"] is False
            assert result["errors"]


class TestTheEndpointNoLongerImportsAMissingSymbol:
    def test_validate_strategy_uses_the_real_validator(self):
        import inspect

        from api.nocode import validate_strategy

        source = inspect.getsource(validate_strategy)
        assert "StateMachineEngine" not in source, "still importing a class that does not exist"
        assert "validate_graph" in source
