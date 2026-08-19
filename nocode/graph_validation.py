# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
nocode/graph_validation.py
==========================
Validation for the visual strategy builder's node/edge graphs.

``POST /api/nocode/validate`` used to do::

    from nocode.state_machine import StateMachineEngine
    engine = StateMachineEngine()
    result = engine.validate_graph(nodes=..., edges=...)

Neither name exists. ``nocode/state_machine.py`` is a states-and-transitions
builder, and ``validate_graph`` appears nowhere in the repository, so the import
raised on every request and the endpoint's ``except Exception`` answered
``{"valid": false, ...}`` for every input. A caller could not tell a broken
strategy from a broken endpoint.

The endpoint's docstring is the contract this implements: valid node types,
proper connections, no cycles in execution flow, and required parameters.

``NODE_TYPES`` lives here rather than inside the ``/node-types`` handler where it
used to be. The validator needs the same taxonomy the palette advertises, and a
second copy would drift from the first.
"""

from __future__ import annotations

from typing import Any

NODE_TYPES = {'indicators': [{'id': 'rsi', 'name': 'RSI', 'params': ['period'], 'outputs': ['value']},
                {'id': 'macd',
                 'name': 'MACD',
                 'params': ['fast', 'slow', 'signal'],
                 'outputs': ['macd', 'signal', 'histogram']},
                {'id': 'atr', 'name': 'ATR', 'params': ['period'], 'outputs': ['value']},
                {'id': 'bollinger',
                 'name': 'Bollinger Bands',
                 'params': ['period', 'std_dev'],
                 'outputs': ['upper', 'middle', 'lower']},
                {'id': 'ema', 'name': 'EMA', 'params': ['period'], 'outputs': ['value']},
                {'id': 'sma', 'name': 'SMA', 'params': ['period'], 'outputs': ['value']},
                {'id': 'stochastic',
                 'name': 'Stochastic',
                 'params': ['k_period', 'd_period'],
                 'outputs': ['k', 'd']},
                {'id': 'adx',
                 'name': 'ADX',
                 'params': ['period'],
                 'outputs': ['value', 'plus_di', 'minus_di']}],
 'conditions': [{'id': 'crossover',
                 'name': 'Crossover',
                 'inputs': ['line_a', 'line_b'],
                 'outputs': ['signal']},
                {'id': 'threshold',
                 'name': 'Threshold',
                 'inputs': ['value'],
                 'params': ['level', 'direction'],
                 'outputs': ['signal']},
                {'id': 'time_filter',
                 'name': 'Time Filter',
                 'params': ['start_hour', 'end_hour', 'days'],
                 'outputs': ['allowed']},
                {'id': 'spread_filter',
                 'name': 'Spread Filter',
                 'params': ['max_spread_pips'],
                 'outputs': ['allowed']}],
 'actions': [{'id': 'buy', 'name': 'Buy', 'inputs': ['signal'], 'params': ['lot_size']},
             {'id': 'sell', 'name': 'Sell', 'inputs': ['signal'], 'params': ['lot_size']},
             {'id': 'close_all', 'name': 'Close All', 'inputs': ['signal']},
             {'id': 'trailing_stop',
              'name': 'Trailing Stop',
              'inputs': ['position'],
              'params': ['distance_pips']}],
 'ml_nodes': [{'id': 'ml_predict',
               'name': 'ML Prediction',
               'params': ['model_name', 'confidence_threshold'],
               'outputs': ['prediction', 'confidence']},
              {'id': 'sentiment_score',
               'name': 'Sentiment Score',
               'params': ['source'],
               'outputs': ['score', 'direction']},
              {'id': 'anomaly_detect',
               'name': 'Anomaly Detection',
               'params': ['sensitivity'],
               'outputs': ['is_anomaly', 'score']}],
 'risk': [{'id': 'position_size',
           'name': 'Position Sizer',
           'params': ['risk_percent', 'method'],
           'outputs': ['lot_size']},
          {'id': 'max_drawdown',
           'name': 'Max Drawdown Guard',
           'params': ['max_dd_percent'],
           'outputs': ['allowed']},
          {'id': 'correlation_filter',
           'name': 'Correlation Filter',
           'params': ['max_correlation'],
           'outputs': ['allowed']}]}


# Categories whose nodes can actually place or modify an order. A graph without
# one can never trade, which is worth telling the user without failing them.
_ACTION_CATEGORIES = frozenset({"actions"})


def _index_types() -> dict[str, dict[str, Any]]:
    """Flatten NODE_TYPES to {type_id: spec} with its category attached."""
    index: dict[str, dict[str, Any]] = {}
    for category, items in NODE_TYPES.items():
        for item in items:
            index[item["id"]] = {**item, "category": category}
    return index


KNOWN_TYPES: dict[str, dict[str, Any]] = _index_types()


def _has_cycle(node_ids: set[str], edges: list[tuple[str, str]]) -> list[str] | None:
    """Return one cycle as a list of node ids, or None.

    Iterative DFS with an explicit colouring, so a diamond (two paths that
    reconverge) is not mistaken for a loop the way a plain visited-set would.
    """
    adjacency: dict[str, list[str]] = {n: [] for n in node_ids}
    for source, target in edges:
        adjacency[source].append(target)

    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(node_ids, WHITE)

    for root in node_ids:
        if colour[root] != WHITE:
            continue
        stack: list[tuple[str, int]] = [(root, 0)]
        path: list[str] = []
        colour[root] = GREY
        path.append(root)
        while stack:
            node, index = stack[-1]
            if index < len(adjacency[node]):
                stack[-1] = (node, index + 1)
                nxt = adjacency[node][index]
                if colour[nxt] == GREY:
                    return path[path.index(nxt) :] + [nxt]
                if colour[nxt] == WHITE:
                    colour[nxt] = GREY
                    path.append(nxt)
                    stack.append((nxt, 0))
            else:
                colour[node] = BLACK
                stack.pop()
                if path:
                    path.pop()
    return None


def validate_graph(nodes: Any, edges: Any) -> dict[str, Any]:
    """Validate a no-code strategy graph.

    Returns ``{"valid": bool, "errors": [str], "warnings": [str]}`` — the shape
    the endpoint already returned from its error branch, so the response
    contract is unchanged.

    Never raises. Malformed input is a finding, not a 500: this is a validation
    endpoint, and turning bad input into a server error would tell the caller
    the wrong thing.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(nodes, list):
        return {"valid": False, "errors": [f"nodes must be a list, got {type(nodes).__name__}"], "warnings": []}
    if not isinstance(edges, list):
        return {"valid": False, "errors": [f"edges must be a list, got {type(edges).__name__}"], "warnings": []}

    # ── Nodes ────────────────────────────────────────────────────────────────
    seen_ids: set[str] = set()
    categories_present: set[str] = set()

    for position, node in enumerate(nodes):
        label = f"node[{position}]"
        if not isinstance(node, dict):
            errors.append(f"{label} must be an object, got {type(node).__name__}")
            continue

        node_id = node.get("id")
        if node_id is None or not isinstance(node_id, str) or not node_id:
            errors.append(f"{label} has no usable 'id'")
        elif node_id in seen_ids:
            errors.append(f"duplicate node id {node_id!r}")
        else:
            seen_ids.add(node_id)
            label = f"node {node_id!r}"

        node_type = node.get("type")
        if not node_type:
            errors.append(f"{label} has no 'type'")
            continue

        spec = KNOWN_TYPES.get(node_type)
        if spec is None:
            errors.append(f"{label} has unknown type {node_type!r}")
            continue

        categories_present.add(spec["category"])

        params = node.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            errors.append(f"{label} 'params' must be an object, got {type(params).__name__}")
            continue

        for required in spec.get("params", []):
            if required not in params:
                errors.append(f"{label} ({node_type}) is missing required parameter {required!r}")

    # ── Edges ────────────────────────────────────────────────────────────────
    resolved_edges: list[tuple[str, str]] = []
    for position, edge in enumerate(edges):
        label = f"edge[{position}]"
        if not isinstance(edge, dict):
            errors.append(f"{label} must be an object, got {type(edge).__name__}")
            continue
        source = edge.get("source")
        target = edge.get("target")
        for role, value in (("source", source), ("target", target)):
            if not isinstance(value, str) or not value:
                errors.append(f"{label} has no usable {role!r}")
            elif value not in seen_ids:
                errors.append(f"{label} {role} {value!r} does not match any node id")
        if isinstance(source, str) and isinstance(target, str) and source in seen_ids and target in seen_ids:
            resolved_edges.append((source, target))

    # ── Execution flow ───────────────────────────────────────────────────────
    if seen_ids and resolved_edges:
        cycle = _has_cycle(seen_ids, resolved_edges)
        if cycle:
            errors.append("execution flow contains a cycle: " + " -> ".join(cycle))

    # ── Advisory ─────────────────────────────────────────────────────────────
    if not nodes:
        warnings.append("strategy is empty — add at least one indicator and one action node")
    elif not categories_present & _ACTION_CATEGORIES:
        warnings.append("strategy has no action node, so it can never open or close a position")

    return {"valid": not errors, "errors": errors, "warnings": warnings}
