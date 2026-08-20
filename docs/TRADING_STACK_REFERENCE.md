# Trading Stack Reference

A curated list of libraries, repositories, and tools for building large-scale
trading applications. Saved as a reference; nothing here is a dependency of
HOPEFX today.

> **Link check — 2026-08-20.** All 13 GitHub repositories below were verified to
> exist, and the npm/PyPI packages named (`lightweight-charts`, `ccxt`,
> `skills`, `@21st-dev/cli`) all resolve on their registries.
>
> **Relevance note.** HOPEFX trades XAUUSD through OANDA and MT5. Sections 3, 6,
> 7, and parts of 10 are crypto-exchange specific (CCXT, Freqtrade, Jesse,
> Hummingbot) and would only apply if the platform expands beyond FX/metals.
> Sections 1, 2, 4, 5, and 9 map directly onto work this repo already does.

---

## 1. Charts – Real-time Financial Charting

**TradingView Lightweight Charts**
https://github.com/tradingview/lightweight-charts

**Purpose:** High-performance, lightweight HTML5 canvas charting library designed specifically for financial data. Industry standard for professional trading interfaces.

**Installation:**

```bash
npm install lightweight-charts
```

**AI Agent Skill:**

```bash
npx skills add https://github.com/tradingview/lightweight-charts
```

**Best for:** Candlestick charts, real-time price updates, technical overlays, and responsive trading dashboards.

---

## 2. Front-end & UI/UX – Professional Trading Interfaces

**Strata Pro Crypto UI**
https://github.com/bymilon/strata-pro-crypto-ui

**Purpose:** Premium, production-ready React trading dashboard built with TypeScript, Vite, Tailwind CSS, and Lightweight Charts. Excellent visual foundation for crypto and fintech products.

**Installation:**

```bash
git clone https://github.com/bymilon/strata-pro-crypto-ui.git
cd strata-pro-crypto-ui
npm install
npm run dev
```

**Best for:** Dark-themed trading dashboards, order books, portfolio views, and modern UI/UX.

**Open Exchange Trading UI**
https://github.com/openexch/trading-ui

**Purpose:** Complete React/TypeScript trading interface featuring real-time order book, live trade feed, order entry forms, and account management.

**Installation:**

```bash
git clone https://github.com/openexch/trading-ui.git
cd trading-ui
npm install
npm run dev
```

**Best for:** Full trading terminal layout (order book + chart + order form).

**Wick – Headless Trading Components**
https://github.com/wick-trading/Wick

**Purpose:** Framework-agnostic, unstyled Web Components for trading interfaces (order book, price ticker, trade feed). Similar philosophy to shadcn/ui but specialized for trading.

**Best for:** Custom design systems that need flexible, high-performance trading primitives.

**Recommended Front-end Stack:**
React 19 + TypeScript + Vite + Tailwind CSS + shadcn/ui + Lightweight Charts

> This is already HOPEFX's `frontend/` stack, minus Lightweight Charts.

---

## 3. Exchange Connectivity & Order Execution

**CCXT**
https://github.com/ccxt/ccxt

**Purpose:** Unified cryptocurrency trading library supporting 100+ exchanges. Handles market data, account balances, and order placement with a consistent API across languages.

**Installation:**

```bash
# Python
pip install ccxt

# JavaScript / TypeScript
npm install ccxt
```

**AI Agent Skill:**

```bash
npx skills add ccxt/ccxt
```

**Best for:** Connecting to exchanges, fetching real-time data, and placing orders reliably.

---

## 4. High-Performance Trading Engine

**NautilusTrader**
https://github.com/nautechsystems/nautilus_trader

**Purpose:** Production-grade algorithmic trading platform with a Rust core and Python API. Designed for high-performance backtesting and live trading with deterministic execution.

**Installation:**

```bash
pip install nautilus_trader
```

**Best for:** Serious quantitative systems requiring low latency, accuracy, and parity between backtest and live environments.

---

## 5. Institutional Algorithmic Trading Engine

**QuantConnect Lean**
https://github.com/QuantConnect/Lean

**Purpose:** Open-source institutional-grade algorithmic trading engine supporting multi-asset strategies, extensive data handling, and live deployment.

**Installation:**

```bash
git clone https://github.com/QuantConnect/Lean.git
# Follow official documentation for Docker or local setup
```

**Best for:** Multi-asset research, backtesting, and professional strategy development.

---

## 6. Crypto Trading Frameworks

**Freqtrade**
https://github.com/freqtrade/freqtrade

**Purpose:** Mature, free, and open-source crypto trading bot with backtesting, hyperparameter optimization, and live trading capabilities.

**Installation:**

```bash
git clone https://github.com/freqtrade/freqtrade.git
cd freqtrade
./setup.sh -i
```

**Best for:** Strategy development, automated crypto trading, and machine-learning assisted optimization.

**Jesse**
https://github.com/jesse-ai/jesse

**Purpose:** Advanced yet simple Python framework for researching, backtesting, optimizing, and live-trading cryptocurrency strategies with high accuracy.

**Installation:**

```bash
pip install jesse
```

**Best for:** Clean strategy code, accurate backtesting, and AI-assisted strategy writing.

---

## 7. Market Making & High-Frequency Style Trading

**Hummingbot**
https://github.com/hummingbot/hummingbot

**Purpose:** Open-source framework for creating and deploying high-frequency market-making and arbitrage strategies across centralized and decentralized exchanges.

**Installation:**

```bash
git clone https://github.com/hummingbot/hummingbot.git
cd hummingbot
make setup
make deploy
```

**Best for:** Liquidity provision, market making, and cross-exchange strategies.

---

## 8. Full Quantitative Trading Platform

**vn.py**
https://github.com/vnpy/vnpy

**Purpose:** Comprehensive open-source quantitative trading platform with extensive broker and exchange connectors, strategy engines, and real-time trading capabilities.

**Best for:** Full-stack quantitative systems, especially in futures and multi-market environments.

---

## 9. Financial Data & Research Platform

**OpenBB**
https://github.com/OpenBB-finance/OpenBB

**Purpose:** Open-source financial data platform that aggregates market data, fundamentals, news, and analytics. Highly compatible with AI agents and research workflows.

**Installation:**

```bash
pip install openbb
```

**Best for:** Market research, data analysis, and feeding high-quality data into trading systems and AI agents.

---

## 10. MCP Servers (Model Context Protocol) for AI Agents

**Hummingbot MCP**
https://github.com/hummingbot/mcp

**Purpose:** Allows AI assistants (Claude, Cursor, ChatGPT, etc.) to control Hummingbot trading bots, manage portfolios, place orders, and monitor performance through natural language.

**Best for:** Giving AI agents direct control over live trading infrastructure.

**OpenBB Agent / MCP Support**
https://github.com/OpenBB-finance/OpenBB

**Purpose:** Enables AI agents to access comprehensive financial data, run analysis, and build research workflows.

**Additional Recommended Finance MCP Servers:**

- Alpha Vantage MCP – Market data and technical indicators
- Alpaca MCP – Stock, ETF, and options trading execution
- CCXT-based MCP servers – Crypto market data and order management

---

## Recommended Starting Stack for AI-Assisted Development

1. **Front-end:** Strata Pro UI + Lightweight Charts
2. **Connectivity:** CCXT + AI Skill
3. **Strategy Engine:** Jesse or NautilusTrader
4. **AI Control Layer:** Hummingbot MCP + OpenBB

---

## Before adopting anything here

HOPEFX is a money-moving system. Two cautions that apply to this whole list:

- **Anything that can place orders** (CCXT, Hummingbot MCP, Alpaca MCP) must sit
  behind the existing pre-trade risk gate in `risk/manager.py` and the kill
  switch — never alongside them. An MCP server that lets an agent place orders
  by natural language is a direct path to capital loss if it bypasses those
  gates. See the trading-system escalation rule in
  `.claude/skills/codebase-audit/references/security-severity-checklist.md`.
- **Engine-scale dependencies** (NautilusTrader, Lean, vn.py, Freqtrade) overlap
  with `core/decision/`, `backtesting/`, and `execution/` rather than slotting
  in beside them. Adopting one is an architecture decision, not an install.
