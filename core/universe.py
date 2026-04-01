# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
core/universe.py
=================
Multi-symbol universe engine.

Manages the set of tradeable instruments, their metadata, data availability,
and routing configuration. Provides a single source of truth for which
symbols are active, their contract specs, and how they map to data feeds.

Wired into: signal_engine, startup_factories, data orchestrator.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default active symbols (override via UNIVERSE_SYMBOLS env var)
_DEFAULT_SYMBOLS = os.getenv(
    "UNIVERSE_SYMBOLS",
    "XAU_USD,XAG_USD,GC=F,SI=F,GLD,IAU",
).split(",")


@dataclass
class InstrumentSpec:
    """Contract specification for a tradeable instrument."""
    symbol: str
    asset_class: str
    """equity, fx, futures, etf, crypto"""
    description: str
    tick_size: float
    lot_size: float
    """Minimum tradeable unit."""
    currency: str = "USD"
    data_feed: str = "auto"
    """Preferred data feed key."""
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


# Built-in instrument catalogue
_INSTRUMENT_CATALOGUE: dict[str, InstrumentSpec] = {
    "XAU_USD": InstrumentSpec(
        symbol="XAU_USD", asset_class="fx", description="Spot Gold vs USD",
        tick_size=0.01, lot_size=1.0, currency="USD",
        data_feed="goldapi", tags=["gold", "precious_metal"],
    ),
    "XAG_USD": InstrumentSpec(
        symbol="XAG_USD", asset_class="fx", description="Spot Silver vs USD",
        tick_size=0.001, lot_size=1.0, currency="USD",
        data_feed="auto", tags=["silver", "precious_metal"],
    ),
    "GC=F": InstrumentSpec(
        symbol="GC=F", asset_class="futures", description="COMEX Gold Futures (front month)",
        tick_size=0.10, lot_size=100.0, currency="USD",
        data_feed="yfinance", tags=["gold", "futures"],
    ),
    "SI=F": InstrumentSpec(
        symbol="SI=F", asset_class="futures", description="COMEX Silver Futures",
        tick_size=0.005, lot_size=5000.0, currency="USD",
        data_feed="yfinance", tags=["silver", "futures"],
    ),
    "GLD": InstrumentSpec(
        symbol="GLD", asset_class="etf", description="SPDR Gold Shares ETF",
        tick_size=0.01, lot_size=1.0, currency="USD",
        data_feed="yfinance", tags=["gold", "etf"],
    ),
    "IAU": InstrumentSpec(
        symbol="IAU", asset_class="etf", description="iShares Gold Trust ETF",
        tick_size=0.01, lot_size=1.0, currency="USD",
        data_feed="yfinance", tags=["gold", "etf"],
    ),
    "HG=F": InstrumentSpec(
        symbol="HG=F", asset_class="futures", description="COMEX Copper Futures",
        tick_size=0.0005, lot_size=25000.0, currency="USD",
        data_feed="yfinance", tags=["copper", "base_metal"],
    ),
    "CL=F": InstrumentSpec(
        symbol="CL=F", asset_class="futures", description="WTI Crude Oil Futures",
        tick_size=0.01, lot_size=1000.0, currency="USD",
        data_feed="yfinance", tags=["oil", "energy"],
    ),
    "^GSPC": InstrumentSpec(
        symbol="^GSPC", asset_class="equity", description="S&P 500 Index",
        tick_size=0.01, lot_size=1.0, currency="USD",
        data_feed="yfinance", tags=["equity", "sp500"],
    ),
    "DX=F": InstrumentSpec(
        symbol="DX=F", asset_class="futures", description="US Dollar Index Futures",
        tick_size=0.005, lot_size=1000.0, currency="USD",
        data_feed="yfinance", tags=["fx", "dxy"],
    ),
}


class UniverseEngine:
    """
    Multi-symbol universe manager.

    Tracks active instruments, maintains specs, validates symbols,
    and provides routing information to downstream components.
    """

    def __init__(self, initial_symbols: list[str] | None = None) -> None:
        self._specs: dict[str, InstrumentSpec] = dict(_INSTRUMENT_CATALOGUE)
        self._active: set[str] = set()

        symbols = initial_symbols if initial_symbols is not None else _DEFAULT_SYMBOLS
        for sym in symbols:
            sym = sym.strip()
            if sym:
                self.add_symbol(sym)

    # ── Symbol management ──────────────────────────────────────────────────────

    def add_symbol(self, symbol: str, spec: InstrumentSpec | None = None) -> bool:
        """Add symbol to active universe. Returns True if newly added."""
        symbol = symbol.strip().upper()
        if spec is not None:
            self._specs[symbol] = spec
        elif symbol not in self._specs:
            # Auto-create minimal spec for unknown symbols
            self._specs[symbol] = InstrumentSpec(
                symbol=symbol, asset_class="unknown",
                description=f"Auto-registered: {symbol}",
                tick_size=0.01, lot_size=1.0,
            )
        self._active.add(symbol)
        logger.info("Universe: added symbol %s", symbol)
        return True

    def remove_symbol(self, symbol: str) -> bool:
        """Remove symbol from active universe (keep spec)."""
        symbol = symbol.strip().upper()
        removed = symbol in self._active
        self._active.discard(symbol)
        if removed:
            logger.info("Universe: removed symbol %s", symbol)
        return removed

    def enable(self, symbol: str) -> None:
        """Enable trading for a symbol."""
        symbol = symbol.strip().upper()
        if symbol in self._specs:
            self._specs[symbol].enabled = True

    def disable(self, symbol: str) -> None:
        """Disable trading for a symbol (keep in universe)."""
        symbol = symbol.strip().upper()
        if symbol in self._specs:
            self._specs[symbol].enabled = False

    # ── Queries ────────────────────────────────────────────────────────────────

    @property
    def active_symbols(self) -> list[str]:
        """Return sorted list of active symbol names."""
        return sorted(self._active)

    @property
    def tradeable_symbols(self) -> list[str]:
        """Return active symbols that are also enabled for trading."""
        return sorted(
            s for s in self._active
            if self._specs.get(s, InstrumentSpec(s, "", "", 0.01, 1.0)).enabled
        )

    def get_spec(self, symbol: str) -> InstrumentSpec | None:
        """Return InstrumentSpec for symbol, or None if unknown."""
        return self._specs.get(symbol.strip().upper())

    def by_asset_class(self, asset_class: str) -> list[str]:
        """Return active symbols filtered by asset class."""
        return [
            s for s in self._active
            if self._specs.get(s, InstrumentSpec(s, "", "", 0.01, 1.0)).asset_class == asset_class
        ]

    def by_tag(self, tag: str) -> list[str]:
        """Return active symbols that carry a given tag."""
        return [
            s for s in self._active
            if tag in self._specs.get(
                s, InstrumentSpec(s, "", "", 0.01, 1.0)
            ).tags
        ]

    def is_active(self, symbol: str) -> bool:
        """Check if symbol is in active universe."""
        return symbol.strip().upper() in self._active

    def snapshot(self) -> dict[str, Any]:
        """Return serialisable snapshot for API/monitoring."""
        return {
            "active_count": len(self._active),
            "tradeable_count": len(self.tradeable_symbols),
            "symbols": [
                {
                    "symbol": s,
                    "asset_class": self._specs[s].asset_class,
                    "description": self._specs[s].description,
                    "enabled": self._specs[s].enabled,
                    "data_feed": self._specs[s].data_feed,
                    "tags": self._specs[s].tags,
                }
                for s in self.active_symbols
                if s in self._specs
            ],
        }


# Module-level singleton
universe_engine = UniverseEngine()
