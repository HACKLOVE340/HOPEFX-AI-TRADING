# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""§26 — a delegation tree that cannot run away.

The registry note for this row said "recursive delegation does not exist yet to
bound", which was true and circular: nothing delegated, so there was nothing to
bound, so the row stayed staged for as long as it stayed staged. §24's worker
boundary gave it somewhere to live.

## Three bounds, because there are three failure modes

Depth alone is the bound people reach for, and it catches only one of these:

* **depth** — A delegates to B delegates to C, for ever. Caught by `max_depth`.
* **fan-out** — one node delegates to five hundred children, all at depth 1.
  Every one of them is within the depth bound.
* **total descendants** — depth 4 and fan-out 8 are each modest, and together
  they are 4,680 nodes. Neither bound is exceeded; the tree is still a runaway.

Each hop is model spend on a platform that moves money, so all three are
enforced separately and a refusal names which one it was.

## The bound is enforced where the child is CREATED

Not where it finishes, and not where its cost is totalled. `TaskGraph.add()`
makes the same argument for cycles: the moment of creation is the last moment
at which nothing has happened yet. Once a child exists the model call is paid
for, and a bound that notices afterwards is a bound that reports rather than
one that prevents.

## Refusing a child does not fail the tree

The work already done was paid for, and discarding it wastes exactly the spend
this module exists to protect. So a refused child is refused, recorded, and the
parent carries on with what it has.

Recorded, though — never silent. A quietly dropped child is a plan that ran
differently from the plan that was written, which is the argument
`unknown_dependencies()` makes in `graph.py`. `refusals()` names every one.

## Unknown lineage is REFUSED, not treated as a root

This is the fail-closed inversion, and it is the whole security of the thing. A
node presenting a parent this ledger has no record of could be a bug, a
replayed message, or a child trying to restart the count at zero. Admitting it
as a fresh root would hand it a whole new budget — so an unrecognised parent is
a refusal, and `open_root()` is the only way a tree begins.

## Across a process boundary, a grant travels instead of the ledger

A ledger is per-process; a child process has its own, empty. So a child is
handed a `grant` — how many descendants it may create beneath itself, in total
— and its own ledger is seeded with exactly that. A subtree cannot spend more
than it was given, whichever process it runs in.

The grant is decided by the parent at the moment it delegates, and the ledger
charges the parent `1 + grant` for a child: one for the child itself, and the
whole grant because that is the worst case the child may spend. Charging only
for the child would let two siblings each be handed the remaining budget and
each spend it.

**The default grant is zero**, so a delegated task may not delegate further
unless somebody said so in the call that created it.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Final

#: Deliberately small. This bounds a runaway, and a tree that legitimately needs
#: more than this is a design somebody should look at rather than a limit to
#: raise quietly.
DEFAULT_MAX_DEPTH: Final = 3
DEFAULT_MAX_FANOUT: Final = 8
DEFAULT_MAX_DESCENDANTS: Final = 24


class DelegationRefused(RuntimeError):
    """A child was not created, because creating it would breach a bound."""


@dataclass(frozen=True)
class DelegationBounds:
    """What a single delegation tree may grow to."""

    max_depth: int = DEFAULT_MAX_DEPTH
    max_fanout: int = DEFAULT_MAX_FANOUT
    max_descendants: int = DEFAULT_MAX_DESCENDANTS

    def __post_init__(self) -> None:
        for name in ("max_depth", "max_fanout", "max_descendants"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer, got {value!r}")


@dataclass(frozen=True)
class Lineage:
    """Where a unit of work sits in its tree.

    Frozen and picklable on purpose: this is what crosses the process boundary
    in a `TaskContract`, and a mutable lineage is one a child could edit before
    presenting it back.
    """

    root_id: str
    node_id: str
    depth: int
    parent_id: str | None = None
    #: Descendants this node may create beneath it, transitively. Zero means it
    #: is a leaf: it may do work, and it may not delegate.
    grant: int = 0

    def __post_init__(self) -> None:
        if not self.root_id or not self.node_id:
            raise ValueError("a lineage needs a root id and a node id")
        if not isinstance(self.depth, int) or self.depth < 0:
            raise ValueError(f"depth must be a non-negative integer, got {self.depth!r}")
        if not isinstance(self.grant, int) or self.grant < 0:
            raise ValueError(f"grant must be a non-negative integer, got {self.grant!r}")


@dataclass
class _Node:
    lineage: Lineage
    children: int = 0
    #: What is left of this node's grant. Charged `1 + grant` per child.
    remaining: int = 0


@dataclass(frozen=True)
class Refusal:
    """A child that was not created, and the bound that stopped it."""

    parent_id: str
    #: One of `depth`, `fanout`, `descendants`, `unknown_parent`.
    bound: str
    detail: str


class DelegationLedger:
    """The per-process record of who delegated to whom, and how much is left.

    Thread-safe: the job runner admits from its worker threads, and two jobs
    delegating at once against one unguarded counter is how a fan-out bound
    turns into a suggestion.
    """

    def __init__(self, bounds: DelegationBounds | None = None) -> None:
        self._bounds = bounds or DelegationBounds()
        self._nodes: dict[str, _Node] = {}
        self._refusals: list[Refusal] = []
        #: The node this PROCESS is, when it is one. Set by `open_root` and by
        #: `adopt`, so work running inside a child can find its own place in
        #: the tree without every function having to be handed it.
        self._own: Lineage | None = None
        self._lock = threading.Lock()

    @property
    def bounds(self) -> DelegationBounds:
        return self._bounds

    def open_root(self, *, grant: int | None = None) -> Lineage:
        """Begin a tree. The ONLY way a lineage comes into existence.

        A root is not delegation — nobody delegated to it — so it is never
        refused. What it is given is a budget, and everything beneath it spends
        from that.
        """
        allowance = self._bounds.max_descendants if grant is None else grant
        if not isinstance(allowance, int) or allowance < 0:
            raise ValueError(f"grant must be a non-negative integer, got {grant!r}")
        allowance = min(allowance, self._bounds.max_descendants)
        node_id = uuid.uuid4().hex
        lineage = Lineage(root_id=node_id, node_id=node_id, depth=0, parent_id=None, grant=allowance)
        with self._lock:
            self._nodes[node_id] = _Node(lineage=lineage, remaining=allowance)
            self._own = lineage
        return lineage

    def adopt(self, lineage: Lineage) -> Lineage:
        """Seed this process's ledger from a lineage that arrived from elsewhere.

        The counterpart of `open_root` on the far side of a process boundary. It
        trusts the GRANT and nothing else: depth and fan-out are re-checked
        against this ledger's own bounds from here on, and the grant is the
        ceiling the parent already paid for.
        """
        with self._lock:
            self._nodes[lineage.node_id] = _Node(lineage=lineage, remaining=lineage.grant)
            self._own = lineage
        return lineage

    def admit(self, parent: Lineage, *, grant: int = 0) -> Lineage:
        """Create a child of `parent`, or refuse and say which bound stopped it.

        `grant` is what the child may spend beneath itself. It defaults to zero,
        so delegation does not propagate unless somebody asked for it here.
        """
        if not isinstance(grant, int) or isinstance(grant, bool) or grant < 0:
            raise ValueError(f"grant must be a non-negative integer, got {grant!r}")

        with self._lock:
            node = self._nodes.get(parent.node_id)
            if node is None:
                # Fail closed. See the module docstring: admitting an unknown
                # parent as a fresh root hands it a whole new budget, which is
                # precisely what a runaway would need.
                return self._refuse(
                    parent.node_id,
                    "unknown_parent",
                    "this process has no record of the delegating task, so the budget it would spend "
                    "from cannot be known; a tree begins with open_root and nowhere else",
                )

            depth = node.lineage.depth + 1
            if depth > self._bounds.max_depth:
                return self._refuse(
                    parent.node_id,
                    "depth",
                    f"delegating here would reach depth {depth}, and the limit is {self._bounds.max_depth}",
                )

            if node.children + 1 > self._bounds.max_fanout:
                return self._refuse(
                    parent.node_id,
                    "fanout",
                    f"this task has already delegated {node.children} times, and the limit is "
                    f"{self._bounds.max_fanout}",
                )

            # One for the child, plus the whole grant, because the grant is what
            # the child may go on to spend and it is spent from this budget.
            cost = 1 + grant
            if cost > node.remaining:
                return self._refuse(
                    parent.node_id,
                    "descendants",
                    f"a child costing {cost} does not fit in the {node.remaining} this tree has left",
                )

            node.remaining -= cost
            node.children += 1
            child = Lineage(
                root_id=node.lineage.root_id,
                node_id=uuid.uuid4().hex,
                depth=depth,
                parent_id=node.lineage.node_id,
                grant=grant,
            )
            self._nodes[child.node_id] = _Node(lineage=child, remaining=grant)
            return child

    def _refuse(self, parent_id: str, bound: str, detail: str) -> Lineage:
        """Record the refusal, then raise it. Called with the lock held."""
        self._refusals.append(Refusal(parent_id=parent_id, bound=bound, detail=detail))
        raise DelegationRefused(detail)

    def refusals(self) -> tuple[Refusal, ...]:
        """Every child this ledger declined. Never emptied by reading."""
        with self._lock:
            return tuple(self._refusals)

    def remaining(self, lineage: Lineage) -> int | None:
        """What `lineage` may still spend, or None if this ledger has no record."""
        with self._lock:
            node = self._nodes.get(lineage.node_id)
            return None if node is None else node.remaining

    def own(self) -> Lineage | None:
        """This process's own place in the tree, if it has one."""
        with self._lock:
            return self._own

    def report(self) -> dict[str, int]:
        """Counts, for §22. Measured, never asserted."""
        with self._lock:
            return {
                "nodes": len(self._nodes),
                "refused": len(self._refusals),
                "max_depth_seen": max((n.lineage.depth for n in self._nodes.values()), default=0),
            }


_LEDGER: DelegationLedger | None = None
_LEDGER_LOCK = threading.Lock()


def get_ledger() -> DelegationLedger:
    """This process's ledger. One per process, because a ledger is a budget."""
    global _LEDGER
    with _LEDGER_LOCK:
        if _LEDGER is None:
            _LEDGER = DelegationLedger()
        return _LEDGER


def current_lineage() -> Lineage | None:
    """Where the work running in THIS process sits, or None at the top.

    An isolated child sets this when it adopts the lineage that travelled in
    its contract, so a task can delegate without every function signature
    having to carry the tree through it.
    """
    return get_ledger().own()


def reset_for_testing() -> None:
    global _LEDGER
    with _LEDGER_LOCK:
        _LEDGER = None
