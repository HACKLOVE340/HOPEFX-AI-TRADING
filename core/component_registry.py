# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
core/component_registry.py
============================
ComponentRegistry — replaces the 40+ sequential try/except blocks in
startup_event() with a declarative, dependency-aware startup table.

Usage
-----
    registry = ComponentRegistry()

    registry.register("config",       _init_config,       required=True)
    registry.register("database",     _init_database,     required=True,  deps=["config"])
    registry.register("cache",        _init_cache,        required=False, deps=["config"])
    registry.register("risk_manager", _init_risk_manager, required=False, deps=["config"])
    registry.register("broker",       _init_broker,       required=False, deps=["config"])
    registry.register("trade_executor", _init_executor,   required=False,
                       deps=["broker", "risk_manager"])

    results = await registry.start_all(app_state)
    registry.print_table()          # logs a clean startup summary table

Design
------
- Each factory is `async def factory(app_state) -> Any`.
- If a required component fails, startup raises immediately.
- If an optional component fails, it is skipped and its dependents are also
  skipped (with a clear log message explaining why).
- `print_table()` logs a single aligned table so operators see the full
  startup status at a glance instead of scrolling through 40+ log lines.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Component:
    """Registered component descriptor."""

    name: str
    factory: Callable  # async def factory(app_state) -> Any
    required: bool = False  # if True, failure raises RuntimeError
    deps: list[str] = field(default_factory=list)
    # Populated after startup
    status: str = "pending"  # pending | ok | failed | skipped
    instance: Any = None
    error: str | None = None
    elapsed_ms: float = 0.0


class ComponentRegistry:
    """
    Declarative component registry with dependency-aware startup.

    Startup order is determined by topological sort of the dependency graph.
    Components whose dependencies failed are automatically skipped.
    """

    def __init__(self) -> None:
        self._components: dict[str, Component] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        name: str,
        factory: Callable,
        required: bool = False,
        deps: list[str] | None = None,
    ) -> ComponentRegistry:
        """
        Register a component.

        Parameters
        ----------
        name     : Unique component name (also used as app_state attribute key)
        factory  : ``async def factory(app_state) -> instance``
        required : If True, failure aborts startup with RuntimeError
        deps     : Names of components that must succeed before this one runs
        """
        self._components[name] = Component(
            name=name,
            factory=factory,
            required=required,
            deps=deps or [],
        )
        return self

    # ── Startup ───────────────────────────────────────────────────────────────

    async def start_all(self, app_state: Any) -> dict[str, Component]:
        """
        Start all registered components in dependency order.

        Sets ``app_state.<name>`` to the returned instance (or None on failure).
        Returns the full component dict for inspection.
        """
        order = self._topological_sort()

        for name in order:
            comp = self._components[name]

            # Check if any dependency failed or was skipped
            failed_dep = next(
                (
                    d
                    for d in comp.deps
                    if self._components.get(
                        d,
                        Component(name=d, factory=lambda s: None),
                    ).status
                    in ("failed", "skipped")
                ),
                None,
            )
            if failed_dep:
                comp.status = "skipped"
                comp.error = f"dependency '{failed_dep}' failed/skipped"
                logger.warning("⊘ %-30s skipped (dep: %s)", name, failed_dep)
                setattr(app_state, name, None)
                continue

            t0 = time.monotonic()
            try:
                if asyncio.iscoroutinefunction(comp.factory):
                    instance = await comp.factory(app_state)
                else:
                    instance = comp.factory(app_state)
                comp.instance = instance
                comp.status = "ok"
                comp.elapsed_ms = (time.monotonic() - t0) * 1000
                setattr(app_state, name, instance)
                logger.info("✓ %-30s %.0f ms", name, comp.elapsed_ms)
            except Exception as exc:
                comp.status = "failed"
                comp.error = str(exc)
                comp.elapsed_ms = (time.monotonic() - t0) * 1000
                setattr(app_state, name, None)

                if comp.required:
                    logger.critical(
                        "✗ %-30s REQUIRED — aborting startup: %s",
                        name,
                        exc,
                    )
                    raise RuntimeError(
                        f"Required component '{name}' failed: {exc}",
                    ) from exc
                logger.warning("⚠ %-30s %.0f ms — %s", name, comp.elapsed_ms, exc)

        return self._components

    # ── Summary table ─────────────────────────────────────────────────────────

    def print_table(self) -> None:
        """Log a single aligned startup summary table."""
        lines = ["", "┌─ Startup Summary " + "─" * 52 + "┐"]
        for comp in self._components.values():
            icon = {"ok": "✓", "failed": "✗", "skipped": "⊘", "pending": "?"}.get(
                comp.status,
                "?",
            )
            req = "REQ" if comp.required else "opt"
            detail = comp.error or f"{comp.elapsed_ms:.0f} ms"
            lines.append(f"│ {icon} {req} {comp.name:<30} {detail:<25}│")
        lines.append("└" + "─" * 70 + "┘")
        logger.info("\n".join(lines))

    # ── Dependency sort ───────────────────────────────────────────────────────

    def _topological_sort(self) -> list[str]:
        """Kahn's algorithm — raises on cycles."""
        in_degree: dict[str, int] = dict.fromkeys(self._components, 0)
        graph: dict[str, list[str]] = {n: [] for n in self._components}

        for name, comp in self._components.items():
            for dep in comp.deps:
                if dep in self._components:
                    graph[dep].append(name)
                    in_degree[name] += 1

        queue = [n for n, d in in_degree.items() if d == 0]
        order: list[str] = []

        while queue:
            node = queue.pop(0)
            order.append(node)
            for neighbour in graph[node]:
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)

        if len(order) != len(self._components):
            raise RuntimeError("ComponentRegistry: circular dependency detected")

        return order

    # ── Convenience accessors ─────────────────────────────────────────────────

    def get(self, name: str) -> Any | None:
        """Return the started instance for a component, or None."""
        comp = self._components.get(name)
        return comp.instance if comp else None

    def all_required_ok(self) -> bool:
        """True if every required component started successfully."""
        return all(c.status == "ok" for c in self._components.values() if c.required)

    def summary(self) -> dict[str, str]:
        """Return {name: status} dict for health endpoints."""
        return {name: c.status for name, c in self._components.items()}
