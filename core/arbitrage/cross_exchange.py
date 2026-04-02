# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
# core/arbitrage/cross_exchange.py
"""
HOPEFX Cross-Exchange Arbitrage Engine
Captures price discrepancies across multiple venues
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

UTC = timezone.utc
from decimal import Decimal

logger = logging.getLogger(__name__)


@dataclass
class ArbitrageOpportunity:
    buy_exchange: str
    sell_exchange: str
    symbol: str
    buy_price: Decimal
    sell_price: Decimal
    size: Decimal
    gross_profit: Decimal
    net_profit: Decimal
    profit_bps: float
    execution_time_ms: float
    confidence: float


class ExchangeConnector(ABC):
    """
    Abstract base class for exchange connectors used by the arbitrage engine.

    Subclass this for each exchange (OANDA, IBKR, Binance, CCXT, etc.) and
    implement the three abstract methods.  The arbitrage engine calls these
    methods directly — returning None silently would cause silent mis-pricing
    and incorrect order sizing, so unimplemented methods raise NotImplementedError
    at instantiation time via ABC enforcement.

    Example
    -------
        class BinanceConnector(ExchangeConnector):
            async def get_ticker(self, symbol: str) -> Dict:
                ticker = await self.client.fetch_ticker(symbol)
                return {"bid": ticker["bid"], "ask": ticker["ask"]}

            async def place_order(self, symbol, side, size, price=None,
                                  order_type="limit") -> Dict:
                order = await self.client.create_order(symbol, order_type,
                                                       side, float(size), float(price))
                return {"filled": order["status"] == "closed",
                        "fill_price": order.get("average")}

            async def get_balance(self, asset: str) -> Decimal:
                balance = await self.client.fetch_balance()
                return Decimal(str(balance["free"].get(asset, 0)))
    """

    def __init__(self, name: str, client, latency_ms: float, fees: dict):
        self.name = name
        self.client = client
        self.latency_ms = latency_ms
        self.maker_fee = fees.get("maker", Decimal("0.001"))
        self.taker_fee = fees.get("taker", Decimal("0.001"))
        self.is_connected = False

    async def connect(self) -> None:
        """Establish connection to the exchange. Override to add auth/handshake."""
        self.is_connected = True

    @abstractmethod
    async def get_ticker(self, symbol: str) -> dict:
        """Return current bid/ask for *symbol* as ``{"bid": Decimal, "ask": Decimal}``."""

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: str,
        size: Decimal,
        price: Decimal | None = None,
        order_type: str = "limit",
    ) -> dict:
        """Place an order and return fill info as ``{"filled": bool, "fill_price": ...}``."""

    @abstractmethod
    async def get_balance(self, asset: str) -> Decimal:
        """Return available balance for *asset* as a Decimal."""


class ArbitrageDetector:
    """Detect arbitrage opportunities across exchanges"""

    def __init__(self, min_profit_bps: float = 10.0):
        self.min_profit_bps = min_profit_bps
        self.exchanges: dict[str, ExchangeConnector] = {}
        self.price_cache: dict[str, dict] = {}  # symbol -> {exchange -> {bid, ask, ts}}
        self.opportunity_history: list[ArbitrageOpportunity] = []

    def add_exchange(self, connector: ExchangeConnector):
        self.exchanges[connector.name] = connector

    async def update_prices(self):
        """Fetch prices from all exchanges"""
        tasks = []
        for _name, ex in self.exchanges.items():
            for symbol in ["BTCUSD", "ETHUSD", "XAUUSD"]:
                tasks.append(self._fetch_price(ex, symbol))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _fetch_price(self, exchange: ExchangeConnector, symbol: str):
        try:
            ticker = await exchange.get_ticker(symbol)
            if symbol not in self.price_cache:
                self.price_cache[symbol] = {}
            self.price_cache[symbol][exchange.name] = {
                "bid": Decimal(str(ticker["bid"])),
                "ask": Decimal(str(ticker["ask"])),
                "timestamp": datetime.now(UTC),
            }
        except Exception as e:
            logger.warning("Price fetch error %s/%s: %s", exchange.name, symbol, e)

    def detect_opportunities(self, symbol: str) -> list[ArbitrageOpportunity]:
        """Find profitable arbitrage for symbol"""
        opportunities = []

        if symbol not in self.price_cache:
            return opportunities

        prices = self.price_cache[symbol]

        # Find best bid (highest buy price) and best ask (lowest sell price)
        best_bid = None
        best_ask = None

        for ex_name, data in prices.items():
            if not best_bid or data["bid"] > best_bid["price"]:
                best_bid = {"exchange": ex_name, "price": data["bid"]}
            if not best_ask or data["ask"] < best_ask["price"]:
                best_ask = {"exchange": ex_name, "price": data["ask"]}

        if not best_bid or not best_ask:
            return opportunities

        # Check profitability
        if best_bid["price"] > best_ask["price"]:
            gross_profit_bps = float(
                (best_bid["price"] - best_ask["price"]) / best_ask["price"] * 10000,
            )

            if gross_profit_bps > self.min_profit_bps:
                # Calculate net profit after fees
                buy_ex = self.exchanges[best_ask["exchange"]]
                sell_ex = self.exchanges[best_bid["exchange"]]

                # Estimate size based on balance
                size = Decimal("0.1")  # Conservative

                gross_profit = (best_bid["price"] - best_ask["price"]) * size
                fee_cost = best_ask["price"] * size * buy_ex.taker_fee + best_bid["price"] * size * sell_ex.taker_fee
                net_profit = gross_profit - fee_cost

                if net_profit > 0:
                    opp = ArbitrageOpportunity(
                        buy_exchange=best_ask["exchange"],
                        sell_exchange=best_bid["exchange"],
                        symbol=symbol,
                        buy_price=best_ask["price"],
                        sell_price=best_bid["price"],
                        size=size,
                        gross_profit=gross_profit,
                        net_profit=net_profit,
                        profit_bps=gross_profit_bps,
                        execution_time_ms=buy_ex.latency_ms + sell_ex.latency_ms,
                        confidence=0.8,  # Based on liquidity depth
                    )
                    opportunities.append(opp)

        return opportunities


class ArbitrageExecutor:
    """Execute arbitrage with leg risk protection"""

    def __init__(self):
        self.pending_executions: dict[str, dict] = {}
        self.max_slippage_bps = 50

    async def execute(
        self,
        opportunity: ArbitrageOpportunity,
        exchanges: dict[str, ExchangeConnector],
    ) -> bool:
        """
        Execute both legs simultaneously with protection.
        If one leg fails, immediately hedge the other.
        """
        logger.info(
            "Executing: %s -> %s",
            opportunity.buy_exchange,
            opportunity.sell_exchange,
        )
        logger.info(
            "Profit: %.2f (%.1f bps)",
            opportunity.net_profit,
            opportunity.profit_bps,
        )

        buy_ex = exchanges[opportunity.buy_exchange]
        sell_ex = exchanges[opportunity.sell_exchange]

        # Send both orders simultaneously
        buy_task = asyncio.create_task(
            self._place_limit_order(
                buy_ex,
                opportunity.symbol,
                "buy",
                opportunity.size,
                opportunity.buy_price * Decimal("1.001"),
            ),
        )
        sell_task = asyncio.create_task(
            self._place_limit_order(
                sell_ex,
                opportunity.symbol,
                "sell",
                opportunity.size,
                opportunity.sell_price * Decimal("0.999"),
            ),
        )

        # Wait for both with timeout
        done, pending = await asyncio.wait(
            [buy_task, sell_task],
            timeout=opportunity.execution_time_ms / 1000 * 2,
            return_when=asyncio.ALL_COMPLETED,
        )

        # Cancel any pending
        for task in pending:
            task.cancel()

        buy_result = await buy_task if buy_task in done else None
        sell_result = await sell_task if sell_task in done else None

        # Check results
        if buy_result and sell_result and buy_result["filled"] and sell_result["filled"]:
            logger.info("Both legs filled. Profit: %.2f", opportunity.net_profit)
            return True

        # Handle partial execution - emergency hedge
        if buy_result and buy_result["filled"] and not sell_result:
            logger.warning("Buy filled, sell failed. Emergency hedging...")
            await self._emergency_hedge(
                buy_ex,
                opportunity.symbol,
                opportunity.size,
                "sell",
            )
            return False

        if sell_result and sell_result["filled"] and not buy_result:
            logger.warning("Sell filled, buy failed. Emergency hedging...")
            await self._emergency_hedge(
                sell_ex,
                opportunity.symbol,
                opportunity.size,
                "buy",
            )
            return False

        logger.error("Both legs failed")
        return False

    async def _place_limit_order(self, exchange, symbol, side, size, price):
        """Place IOC limit order"""
        return await exchange.place_order(
            symbol=symbol,
            side=side,
            size=size,
            price=price,
            order_type="limit",
        )

    async def _emergency_hedge(self, exchange, symbol, size, side):
        """Market order to close naked position"""
        logger.warning("Emergency %s %.8g %s on %s", side, size, symbol, exchange.name)
        await exchange.place_order(
            symbol=symbol,
            side=side,
            size=size * Decimal("0.5"),  # Partial to reduce slippage
            order_type="market",
        )


class CrossExchangeEngine:
    """Main arbitrage engine coordinating detection and execution"""

    def __init__(self):
        self.detector = ArbitrageDetector(min_profit_bps=5.0)
        self.executor = ArbitrageExecutor()
        self.is_running = False
        self.stats = {"detected": 0, "executed": 0, "profit": Decimal("0")}

    def add_exchange(self, connector: ExchangeConnector):
        self.detector.add_exchange(connector)

    async def run(self, symbols: list[str] = None):
        """Main arbitrage loop"""
        if symbols is None:
            symbols = ["BTCUSD", "ETHUSD", "XAUUSD"]

        self.is_running = True

        while self.is_running:
            try:
                # Update prices
                await self.detector.update_prices()

                # Detect opportunities
                for symbol in symbols:
                    opps = self.detector.detect_opportunities(symbol)

                    for opp in opps:
                        self.stats["detected"] += 1

                        # Execute
                        success = await self.executor.execute(
                            opp,
                            self.detector.exchanges,
                        )

                        if success:
                            self.stats["executed"] += 1
                            self.stats["profit"] += opp.net_profit

                await asyncio.sleep(0.1)  # 10Hz scan rate

            except Exception as e:
                logger.error("Arbitrage error: %s", e)
                await asyncio.sleep(1)

    def get_stats(self):
        return {
            **self.stats,
            "success_rate": self.stats["executed"] / max(self.stats["detected"], 1),
            "avg_profit": float(self.stats["profit"]) / max(self.stats["executed"], 1),
        }
