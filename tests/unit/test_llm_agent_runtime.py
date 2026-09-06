# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_llm_agent_runtime.py
====================================
`brain/llm_agent.py` was 456 statements at 25.51 % — and the covered quarter
was almost entirely the AST sandbox (`tests/unit/test_llm_sandbox.py`).

Everything that *runs* was unverified: the agent's construction and backend
selection, the refinement loop, the walk-forward backtest, the retry/backoff
ladders against both providers, and the chat path that injects live market
state into a prompt. `tests/unit/test_brain_llm_runtime.py` covers the *API*
layer in `api/`, not this module.

Two of these behaviours are load-bearing well beyond a coverage number:

* **The bounded history deque.** `generate_strategy` resets the conversation
  with `clear()` + `append()` precisely so the `maxlen` survives; reassigning a
  plain list there would let history grow without limit across reflection
  iterations and walk the context window off a cliff. Nothing tested that.
* **The 401 short-circuit.** A bad API key must fail immediately. If it fell
  into the retry ladder it would sleep 1s + 2s before returning the same
  answer, on every call, forever.

Network is never touched: `httpx.AsyncClient` and the OpenAI client are both
substituted, and `asyncio.sleep` is neutralised so the backoff ladders are
asserted rather than waited out.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import brain.llm_agent as agent_mod
from brain.llm_agent import (
    AgentResult,
    BacktestResult,
    LLMAgent,
    _load_recent_candles_from_csv,
    _run_backtest,
    create_agent,
)

pytestmark = pytest.mark.unit


# ── helpers ───────────────────────────────────────────────────────────────────


@pytest.fixture
def no_sleep(monkeypatch):
    """Collect backoff delays instead of waiting them out."""
    delays: list[float] = []

    async def _sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    return delays


@pytest.fixture
def anthropic_agent(monkeypatch):
    monkeypatch.setattr(agent_mod, "_LLM_BACKEND", "anthropic", raising=False)
    return LLMAgent(
        api_key="placeholder-key",  # pragma: allowlist secret
        backend="anthropic",
        enable_rag=False,
    )


def _candles(n=120, start=2000.0):
    """OHLCV dicts shaped the way _run_backtest reads them."""
    out = []
    for i in range(n):
        close = start + (i % 10) - 5
        out.append(
            {
                "timestamp": f"2026-01-01T{i % 24:02d}:00:00Z",
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 100,
            }
        )
    return out


class _AlternatingStrategy:
    """Emits BUY then SELL on alternating bars so trades actually close."""

    def __init__(self):
        self.calls = 0

    def analyze(self, data):
        self.calls += 1
        return {"n": len(data.get("candles", []))}

    def generate_signal(self, analysis):
        from strategies.base import Signal, SignalType

        kind = SignalType.BUY if self.calls % 2 else SignalType.SELL
        return Signal(
            signal_type=kind,
            symbol="XAU_USD",
            price=2000.0,
            timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            confidence=0.6,
        )


class _SilentStrategy:
    def analyze(self, data):
        return {}

    def generate_signal(self, analysis):
        return None


class _ExplodingStrategy:
    def analyze(self, data):
        raise ValueError("indicator blew up")

    def generate_signal(self, analysis):  # pragma: no cover - never reached
        return None


def _anthropic_response(text="print('hi')"):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"content": [{"text": text}]})
    return resp


def _patch_httpx(monkeypatch, *responses):
    """Substitute httpx.AsyncClient; each call returns the next response or raises it."""
    import httpx

    queue = list(responses)
    posted: list[dict] = []

    class _Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            posted.append({"url": url, "headers": headers, "json": json})
            item = queue.pop(0) if queue else _anthropic_response()
            if isinstance(item, Exception):
                raise item
            return item

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return posted


def _http_status_error(status, body="boom"):
    import httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, text=body, request=request)
    return httpx.HTTPStatusError("err", request=request, response=response)


# ── candles from CSV ──────────────────────────────────────────────────────────


class TestLoadRecentCandlesFromCsv:
    def test_a_missing_file_is_an_empty_list_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)

        assert _load_recent_candles_from_csv("NOPE") == []

    def test_it_reads_and_normalises_a_csv(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "XAU_USD_H1.csv").write_text(
            "Timestamp,Open,High,Low,Close,Volume\n"
            "2026-01-01T00:00:00Z,2000,2010,1990,2005,100\n"
            "2026-01-01T01:00:00Z,2005,2015,1995,2010,120\n"
        )

        candles = _load_recent_candles_from_csv("XAU_USD", count=10)

        assert len(candles) == 2
        assert candles[0]["close"] == pytest.approx(2005.0)
        assert candles[1]["volume"] == 120
        assert isinstance(candles[0]["open"], float)

    def test_it_honours_the_count_by_taking_the_tail(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        rows = "\n".join(f"2026-01-01T00:00:00Z,1,2,0,{i},1" for i in range(10))
        (tmp_path / "data" / "XAU_USD_H1.csv").write_text("timestamp,open,high,low,close,volume\n" + rows)

        candles = _load_recent_candles_from_csv("XAU_USD", count=3)

        assert [c["close"] for c in candles] == [7.0, 8.0, 9.0]

    def test_a_malformed_csv_degrades_to_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "XAU_USD_H1.csv").write_text("timestamp,open\nnot,a,number,at,all\n")

        assert _load_recent_candles_from_csv("XAU_USD") == []


# ── result dataclasses ────────────────────────────────────────────────────────


class TestBacktestResult:
    def test_a_successful_summary_reports_every_metric(self):
        summary = BacktestResult(1.5, 0.25, -0.1, 0.6, 12).summary()

        assert "Sharpe=1.500" in summary
        assert "Return=25.00%" in summary
        assert "MaxDD=-10.00%" in summary
        assert "WinRate=60.0%" in summary
        assert "Trades=12" in summary

    def test_an_errored_summary_says_so_and_hides_the_zeroes(self):
        summary = BacktestResult(0, 0, 0, 0, 0, error="Not enough candle data").summary()

        assert summary == "Backtest failed: Not enough candle data"
        assert "Sharpe" not in summary


class TestAgentResult:
    def test_it_defaults_to_an_empty_conversation_and_no_error(self):
        result = AgentResult(True, "code", "GeneratedStrategy", None, 1)

        assert result.conversation == []
        assert result.error is None

    def test_every_result_gets_its_own_short_id(self):
        a = AgentResult(True, "", "", None, 1)
        b = AgentResult(True, "", "", None, 1)

        assert a.strategy_id != b.strategy_id
        assert len(a.strategy_id) == 8


# ── walk-forward backtest ─────────────────────────────────────────────────────


class TestRunBacktest:
    def test_too_few_candles_is_a_reported_error_not_a_crash(self):
        result = _run_backtest(_SilentStrategy(), _candles(10))

        assert result.error == "Not enough candle data"
        assert result.trades == 0

    def test_exactly_under_the_floor_is_rejected(self):
        assert _run_backtest(_SilentStrategy(), _candles(59)).error is not None

    def test_at_the_floor_it_runs(self):
        assert _run_backtest(_SilentStrategy(), _candles(60)).error is None

    def test_a_strategy_that_never_signals_takes_no_trades(self):
        result = _run_backtest(_SilentStrategy(), _candles())

        assert result.error is None
        assert result.trades == 0
        assert result.win_rate == 0.0

    def test_an_alternating_strategy_opens_and_closes_positions(self):
        result = _run_backtest(_AlternatingStrategy(), _candles())

        assert result.error is None
        assert result.trades > 0
        assert 0.0 <= result.win_rate <= 1.0

    def test_a_strategy_that_raises_is_swallowed_per_bar(self):
        """One bad bar must not abort the whole backtest."""
        result = _run_backtest(_ExplodingStrategy(), _candles())

        assert result.error is None
        assert result.trades == 0

    def test_the_metrics_are_finite(self):
        import math

        result = _run_backtest(_AlternatingStrategy(), _candles())

        assert math.isfinite(result.sharpe)
        assert math.isfinite(result.total_return)
        assert math.isfinite(result.max_drawdown)

    def test_drawdown_is_never_positive(self):
        assert _run_backtest(_AlternatingStrategy(), _candles()).max_drawdown <= 0.0

    def test_commission_makes_trading_costlier_than_not_trading(self):
        """35 bps a side is real money; a churning strategy must show it."""
        churn = _run_backtest(_AlternatingStrategy(), _candles())
        idle = _run_backtest(_SilentStrategy(), _candles())

        assert churn.total_return < idle.total_return


# ── construction / backend selection ──────────────────────────────────────────


class TestConstruction:
    def test_anthropic_is_the_default_backend(self, monkeypatch):
        monkeypatch.setattr(agent_mod, "_LLM_BACKEND", "anthropic", raising=False)
        a = LLMAgent(api_key="k")

        assert a._backend == "anthropic"

    def test_anthropic_without_a_key_refuses_to_construct(self, monkeypatch):
        monkeypatch.setattr(agent_mod, "_ANTHROPIC_API_KEY", None, raising=False)

        with pytest.raises(ValueError, match="Anthropic API key required"):
            LLMAgent(backend="anthropic")

    def test_a_key_from_the_environment_is_used(self, monkeypatch):
        monkeypatch.setattr(agent_mod, "_ANTHROPIC_API_KEY", "env-key", raising=False)
        a = LLMAgent(backend="anthropic")

        assert a._anthropic_key == "env-key"

    def test_an_unknown_backend_is_rejected_by_name(self):
        with pytest.raises(ValueError, match="Unknown LLM backend"):
            LLMAgent(api_key="k", backend="llama")

    def test_the_backend_name_is_case_insensitive(self):
        assert LLMAgent(api_key="k", backend="ANTHROPIC")._backend == "anthropic"

    def test_openai_without_a_key_refuses_to_construct(self, monkeypatch):
        monkeypatch.setattr(agent_mod, "_OPENAI_API_KEY", None, raising=False)

        with pytest.raises(ValueError, match="OpenAI API key required"):
            LLMAgent(backend="openai")

    def test_constructing_an_openai_agent_builds_no_vendor_client(self, monkeypatch):
        """The agent no longer holds a vendor SDK client — the gateway makes the call.

        This asserted `fake_openai.AsyncOpenAI.assert_called_once_with(api_key=...)`,
        which is the bypass itself: a client constructed here reaches OpenAI
        without the chain, the ceiling, the guardrails or the audit record.
        """
        fake_openai = MagicMock()
        monkeypatch.setitem(__import__("sys").modules, "openai", fake_openai)

        a = LLMAgent(api_key="k", backend="openai")

        assert a._anthropic_key is None
        assert not hasattr(a, "_openai_client")
        fake_openai.AsyncOpenAI.assert_not_called()

    def test_an_explicit_model_overrides_the_default(self):
        assert LLMAgent(api_key="k", backend="anthropic", model="custom-1").model == "custom-1"

    def test_the_history_deque_is_bounded(self, anthropic_agent):
        """Unbounded history is a context-window overflow waiting to happen."""
        expected = 1 + agent_mod._CHAT_MAX_HISTORY_TURNS * 2

        assert anthropic_agent._history.maxlen == expected

    def test_the_rag_store_is_lazy(self, anthropic_agent):
        assert anthropic_agent._vector_store is None


# ── fence stripping ───────────────────────────────────────────────────────────


class TestStripFences:
    def test_plain_code_is_untouched(self):
        assert LLMAgent._strip_fences("x = 1") == "x = 1"

    def test_a_fenced_block_loses_its_fences(self):
        assert LLMAgent._strip_fences("```python\nx = 1\n```") == "x = 1"

    def test_a_bare_fence_is_stripped(self):
        assert LLMAgent._strip_fences("```\nx = 1\n```") == "x = 1"

    def test_multiline_bodies_survive_intact(self):
        assert LLMAgent._strip_fences("```py\na = 1\nb = 2\n```") == "a = 1\nb = 2"

    def test_a_fence_that_is_not_at_the_start_is_left_alone(self):
        text = "note:\n```\nx\n```"

        assert LLMAgent._strip_fences(text) == text


# ── live market context ───────────────────────────────────────────────────────


class TestBuildLiveContext:
    def test_no_broker_means_no_context(self, anthropic_agent, monkeypatch):
        from core.app_state import app_state as live_state

        monkeypatch.setattr(live_state, "broker", None, raising=False)

        assert anthropic_agent._build_live_context() == ""

    def test_a_broker_with_no_prices_means_no_context(self, anthropic_agent, monkeypatch):
        from core.app_state import app_state as live_state

        monkeypatch.setattr(live_state, "broker", SimpleNamespace(market_prices={}), raising=False)

        assert anthropic_agent._build_live_context() == ""

    def test_prices_are_rendered_as_a_snapshot(self, anthropic_agent, monkeypatch):
        from core.app_state import app_state as live_state

        monkeypatch.setattr(
            live_state,
            "broker",
            SimpleNamespace(market_prices={"XAU_USD": 2001.5}),
            raising=False,
        )
        monkeypatch.setattr(live_state, "inference_engine", None, raising=False)

        context = anthropic_agent._build_live_context()

        assert "Live Market Snapshot" in context
        assert "XAU_USD: 2001.5" in context

    def test_at_most_six_symbols_reach_the_prompt(self, anthropic_agent, monkeypatch):
        from core.app_state import app_state as live_state

        monkeypatch.setattr(
            live_state,
            "broker",
            SimpleNamespace(market_prices={f"SYM{i}": float(i) for i in range(20)}),
            raising=False,
        )
        monkeypatch.setattr(live_state, "inference_engine", None, raising=False)

        lines = anthropic_agent._build_live_context().splitlines()

        assert len([ln for ln in lines if ln.startswith("- ")]) == 6

    def test_the_ml_engine_health_is_appended_when_present(self, anthropic_agent, monkeypatch):
        from core.app_state import app_state as live_state

        monkeypatch.setattr(
            live_state,
            "broker",
            SimpleNamespace(market_prices={"XAU_USD": 2000.0}),
            raising=False,
        )
        monkeypatch.setattr(
            live_state,
            "inference_engine",
            SimpleNamespace(health=lambda: {"model_version": "v9", "predict_count": 3, "fallback_count": 1}),
            raising=False,
        )

        context = anthropic_agent._build_live_context()

        assert "model=v9" in context
        assert "predictions=3" in context
        assert "fallbacks=1" in context

    def test_a_broken_inference_engine_does_not_lose_the_prices(self, anthropic_agent, monkeypatch):
        """Health is a nice-to-have; prices are the point."""
        from core.app_state import app_state as live_state

        def _boom():
            raise RuntimeError("engine down")

        monkeypatch.setattr(
            live_state,
            "broker",
            SimpleNamespace(market_prices={"XAU_USD": 2000.0}),
            raising=False,
        )
        monkeypatch.setattr(
            live_state,
            "inference_engine",
            SimpleNamespace(health=_boom),
            raising=False,
        )

        context = anthropic_agent._build_live_context()

        assert "XAU_USD: 2000.0" in context
        assert "ML Engine" not in context


# ── RAG context ───────────────────────────────────────────────────────────────


class TestFetchRagContext:
    @pytest.mark.asyncio
    async def test_it_is_skipped_when_disabled(self):
        a = LLMAgent(api_key="k", backend="anthropic", enable_rag=False)

        assert await a._fetch_rag_context() == ""

    @pytest.mark.asyncio
    async def test_no_candles_anywhere_means_no_context(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        a = LLMAgent(api_key="k", backend="anthropic", enable_rag=True)
        a._vector_store = MagicMock()

        assert await a._fetch_rag_context() == ""

    @pytest.mark.asyncio
    async def test_a_hit_is_wrapped_with_its_heading(self, monkeypatch):
        a = LLMAgent(
            api_key="k",
            backend="anthropic",
            enable_rag=True,
            candle_fetcher=AsyncMock(return_value=_candles(60)),
        )
        a._vector_store = MagicMock()
        a._vector_store.rag_context_for_llm.return_value = "regime A matched"

        context = await a._fetch_rag_context()

        assert "Market Context (RAG" in context
        assert "regime A matched" in context

    @pytest.mark.asyncio
    async def test_a_miss_returns_nothing_rather_than_the_word_no(self, monkeypatch):
        a = LLMAgent(
            api_key="k",
            backend="anthropic",
            enable_rag=True,
            candle_fetcher=AsyncMock(return_value=_candles(60)),
        )
        a._vector_store = MagicMock()
        a._vector_store.rag_context_for_llm.return_value = "No similar setups found"

        assert await a._fetch_rag_context() == ""

    @pytest.mark.asyncio
    async def test_a_failing_fetcher_falls_through_to_the_csv(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        a = LLMAgent(
            api_key="k",
            backend="anthropic",
            enable_rag=True,
            candle_fetcher=AsyncMock(side_effect=RuntimeError("no feed")),
        )
        a._vector_store = MagicMock()

        # No CSV either, so the result is empty — but crucially, no exception.
        assert await a._fetch_rag_context() == ""

    @pytest.mark.asyncio
    async def test_a_broken_vector_store_is_non_fatal(self):
        a = LLMAgent(
            api_key="k",
            backend="anthropic",
            enable_rag=True,
            candle_fetcher=AsyncMock(return_value=_candles(60)),
        )
        a._vector_store = MagicMock()
        a._vector_store.rag_context_for_llm.side_effect = RuntimeError("index corrupt")

        assert await a._fetch_rag_context() == ""


# ── the model call ────────────────────────────────────────────────────────────
#
# `_call_anthropic` and `_call_openai` are gone. They posted to
# api.anthropic.com and called the `openai` SDK inline, each with its own retry
# loop that retried the SAME vendor with backoff -- the one thing that does not
# help when that vendor is what is down -- and neither had a spend ceiling, an
# audit record, or an input guardrail. The agent turns operator text into
# trading strategies, so it is exactly the caller those controls exist for.
#
# What replaced them is `_call_gateway`, and the behaviours the old tests
# asserted now belong in two places: transport (retry, status mapping,
# fall-through to a second vendor) is the gateway's, tested in
# tests/unit/test_ai_gateway*.py; the agent's own contract -- fence stripping,
# history handling, and turning a failure into ("", reason) rather than an
# exception -- is tested here.


class _StubResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.provider = "anthropic"
        self.model = "claude-opus-5"
        self.latency_ms = 1.0
        self.cost_usd = 0.0
        self.tokens_in = 1
        self.tokens_out = 1


def _patch_gateway(monkeypatch, *, result=None, raises=None):
    """Stub the gateway at its boundary and capture the request it was given."""
    import ai.gateway.adapters as adapters_module
    import ai.gateway.client as client_module

    captured: dict = {}

    class _Client:
        def __init__(self, providers=None, **_kw) -> None:
            self.providers = providers

        def call_sync(self, request, *, operator):
            captured["request"] = request
            captured["operator"] = operator
            if raises is not None:
                raise raises
            return result

    monkeypatch.setattr(client_module, "GatewayClient", _Client)
    monkeypatch.setattr(adapters_module, "build_providers", lambda: {"anthropic": object()})
    return captured


class TestCallGateway:
    @pytest.mark.asyncio
    async def test_a_successful_call_returns_stripped_content(self, anthropic_agent, monkeypatch):
        _patch_gateway(monkeypatch, result=_StubResponse("```python\nx = 1\n```"))

        content, error = await anthropic_agent._call_gateway([{"role": "user", "content": "hi"}], update_history=False)

        assert error is None
        assert content == "x = 1"

    @pytest.mark.asyncio
    async def test_the_system_role_is_labelled_not_dropped(self, anthropic_agent, monkeypatch):
        """The gateway speaks in prompts; a system instruction must stay distinguishable."""
        captured = _patch_gateway(monkeypatch, result=_StubResponse("ok"))

        await anthropic_agent._call_gateway(
            [{"role": "system", "content": "SYS"}, {"role": "user", "content": "hi"}],
            update_history=False,
        )

        prompt = captured["request"].prompt
        assert "[system]" in prompt and "SYS" in prompt
        assert prompt.rstrip().endswith("hi")

    @pytest.mark.asyncio
    async def test_empty_messages_do_not_reach_a_provider(self, anthropic_agent, monkeypatch):
        captured = _patch_gateway(monkeypatch, result=_StubResponse("ok"))

        content, error = await anthropic_agent._call_gateway([{"role": "user", "content": "  "}], update_history=False)

        assert content == ""
        assert error is not None
        assert "request" not in captured, "an empty prompt was still sent and billed"

    @pytest.mark.asyncio
    async def test_history_is_appended_only_when_asked(self, anthropic_agent, monkeypatch):
        _patch_gateway(monkeypatch, result=_StubResponse("answer"))

        before = len(anthropic_agent._history)
        await anthropic_agent._call_gateway([{"role": "user", "content": "hi"}], update_history=False)
        assert len(anthropic_agent._history) == before

        await anthropic_agent._call_gateway([{"role": "user", "content": "hi"}], update_history=True)
        assert anthropic_agent._history[-1] == {"role": "assistant", "content": "answer"}

    @pytest.mark.asyncio
    async def test_generation_is_billed_to_the_agent_not_a_person(self, anthropic_agent, monkeypatch):
        """A strategy-search loop must not exhaust an operator's ceiling."""
        captured = _patch_gateway(monkeypatch, result=_StubResponse("ok"))

        await anthropic_agent._call_gateway([{"role": "user", "content": "hi"}], update_history=False)

        assert captured["operator"] == "strategy-agent"

    @pytest.mark.asyncio
    async def test_an_unconfigured_deployment_reports_it_rather_than_raising(self, anthropic_agent, monkeypatch):
        import ai.gateway.adapters as adapters_module

        monkeypatch.setattr(adapters_module, "build_providers", lambda: {})

        content, error = await anthropic_agent._call_gateway([{"role": "user", "content": "hi"}], update_history=False)

        assert content == ""
        assert "No LLM vendor is configured" in (error or "")

    @pytest.mark.asyncio
    async def test_a_budget_refusal_is_returned_as_an_error_not_raised(self, anthropic_agent, monkeypatch):
        """Callers above this expect (content, error); an exception would abort the loop."""
        from ai.gateway.client import BudgetExceeded

        _patch_gateway(monkeypatch, raises=BudgetExceeded("operator budget exhausted"))

        content, error = await anthropic_agent._call_gateway([{"role": "user", "content": "hi"}], update_history=False)

        assert content == ""
        assert "budget" in (error or "").lower()

    @pytest.mark.asyncio
    async def test_a_guardrail_rejection_is_returned_as_an_error(self, anthropic_agent, monkeypatch):
        from ai.guardrails.output import GuardrailViolation

        _patch_gateway(monkeypatch, raises=GuardrailViolation("unsafe instruction pattern"))

        content, error = await anthropic_agent._call_gateway([{"role": "user", "content": "hi"}], update_history=False)

        assert content == ""
        assert "Guardrail" in (error or "")

    @pytest.mark.asyncio
    async def test_every_leg_failing_is_reported_not_raised(self, anthropic_agent, monkeypatch):
        from ai.gateway.client import NoProviderAvailable

        _patch_gateway(monkeypatch, raises=NoProviderAvailable("no model served role 'reasoning'"))

        content, error = await anthropic_agent._call_gateway([{"role": "user", "content": "hi"}], update_history=False)

        assert content == ""
        assert "No LLM vendor answered" in (error or "")


class TestBackendDispatch:
    @pytest.mark.asyncio
    async def test_call_llm_uses_the_history_and_updates_it(self, anthropic_agent):
        with patch.object(anthropic_agent, "_call_gateway", new=AsyncMock(return_value=("x", None))) as spy:
            await anthropic_agent._call_llm()

        assert spy.call_args.kwargs["update_history"] is True

    @pytest.mark.asyncio
    async def test_call_llm_with_messages_does_not_touch_history(self, anthropic_agent):
        with patch.object(anthropic_agent, "_call_gateway", new=AsyncMock(return_value=("x", None))) as spy:
            await anthropic_agent._call_llm_with_messages([{"role": "user", "content": "hi"}])

        assert spy.call_args.kwargs["update_history"] is False

    @pytest.mark.asyncio
    async def test_an_openai_agent_takes_the_same_path(self, monkeypatch):
        """One door. The chain decides the vendor, not the agent's constructor."""
        monkeypatch.setitem(__import__("sys").modules, "openai", MagicMock())
        a = LLMAgent(api_key="k", backend="openai")

        with patch.object(a, "_call_gateway", new=AsyncMock(return_value=("x", None))) as spy:
            await a._call_llm()

        assert spy.called


# ── the refinement loop ───────────────────────────────────────────────────────


_GOOD_CODE = "class GeneratedStrategy:\n    pass\n"


class TestGenerateStrategy:
    @pytest.mark.asyncio
    async def test_an_llm_error_returns_a_failed_result_on_the_first_pass(self, anthropic_agent):
        anthropic_agent._call_llm = AsyncMock(return_value=("", "provider down"))

        result = await anthropic_agent.generate_strategy("make me money")

        assert result.success is False
        assert result.error == "provider down"
        assert result.iterations == 1

    @pytest.mark.asyncio
    async def test_the_conversation_is_seeded_with_system_then_user(self, anthropic_agent):
        anthropic_agent._call_llm = AsyncMock(return_value=("", "stop here"))

        result = await anthropic_agent.generate_strategy("mean reversion please")

        assert result.conversation[0]["role"] == "system"
        assert result.conversation[1] == {"role": "user", "content": "mean reversion please"}

    @pytest.mark.asyncio
    async def test_resetting_the_conversation_keeps_the_deque_bounded(self, anthropic_agent):
        """A plain-list reassignment here would silently drop maxlen."""
        anthropic_agent._call_llm = AsyncMock(return_value=("", "stop"))
        expected = anthropic_agent._history.maxlen

        await anthropic_agent.generate_strategy("first")
        await anthropic_agent.generate_strategy("second")

        assert anthropic_agent._history.maxlen == expected

    @pytest.mark.asyncio
    async def test_a_compile_error_is_fed_back_and_retried(self, anthropic_agent):
        anthropic_agent._call_llm = AsyncMock(return_value=("import os\n", None))

        result = await anthropic_agent.generate_strategy("do something banned")

        assert anthropic_agent._call_llm.await_count == anthropic_agent.max_iterations
        assert result.success is False
        assert any("compile error" in m["content"] for m in anthropic_agent._history if m["role"] == "user")

    @pytest.mark.asyncio
    async def test_with_no_candles_a_compiling_strategy_is_accepted(self, anthropic_agent):
        anthropic_agent._call_llm = AsyncMock(return_value=(_GOOD_CODE, None))
        with patch.object(agent_mod, "_compile_strategy", return_value=(object(), None)):
            result = await anthropic_agent.generate_strategy("anything")

        assert result.success is True
        assert result.backtest is None
        assert result.iterations == 1

    @pytest.mark.asyncio
    async def test_a_backtest_over_target_ends_the_loop_early(self, anthropic_agent):
        anthropic_agent.candle_fetcher = AsyncMock(return_value=_candles())
        anthropic_agent.target_sharpe = 1.0
        anthropic_agent._call_llm = AsyncMock(return_value=(_GOOD_CODE, None))

        with (
            patch.object(agent_mod, "_compile_strategy", return_value=(object(), None)),
            patch.object(agent_mod, "_run_backtest", return_value=BacktestResult(2.0, 0.3, -0.05, 0.7, 9)),
        ):
            result = await anthropic_agent.generate_strategy("anything")

        assert result.success is True
        assert result.iterations == 1
        assert result.backtest.sharpe == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_a_backtest_under_target_exhausts_the_iterations(self, anthropic_agent):
        anthropic_agent.candle_fetcher = AsyncMock(return_value=_candles())
        anthropic_agent.target_sharpe = 5.0
        anthropic_agent._call_llm = AsyncMock(return_value=(_GOOD_CODE, None))

        with (
            patch.object(agent_mod, "_compile_strategy", return_value=(object(), None)),
            patch.object(agent_mod, "_run_backtest", return_value=BacktestResult(0.5, 0.0, -0.2, 0.4, 4)),
        ):
            result = await anthropic_agent.generate_strategy("anything")

        assert result.success is False
        assert anthropic_agent._call_llm.await_count == anthropic_agent.max_iterations

    @pytest.mark.asyncio
    async def test_a_failing_candle_fetcher_disables_backtesting_rather_than_the_run(self, anthropic_agent):
        anthropic_agent.candle_fetcher = AsyncMock(side_effect=RuntimeError("feed down"))
        anthropic_agent._call_llm = AsyncMock(return_value=(_GOOD_CODE, None))

        with patch.object(agent_mod, "_compile_strategy", return_value=(object(), None)):
            result = await anthropic_agent.generate_strategy("anything")

        assert result.success is True
        assert result.backtest is None

    @pytest.mark.asyncio
    async def test_a_reflection_prompt_carries_the_backtest_summary(self, anthropic_agent):
        anthropic_agent.candle_fetcher = AsyncMock(return_value=_candles())
        anthropic_agent.target_sharpe = 5.0
        anthropic_agent._call_llm = AsyncMock(return_value=(_GOOD_CODE, None))

        with (
            patch.object(agent_mod, "_compile_strategy", return_value=(object(), None)),
            patch.object(agent_mod, "_run_backtest", return_value=BacktestResult(0.5, 0.0, -0.2, 0.4, 4)),
        ):
            await anthropic_agent.generate_strategy("anything")

        assert any("Sharpe=0.500" in m["content"] for m in anthropic_agent._history if m["role"] == "user")


# ── chat ──────────────────────────────────────────────────────────────────────


class TestChat:
    @pytest.mark.asyncio
    async def test_a_fresh_session_is_seeded_with_the_assistant_prompt(self, anthropic_agent):
        anthropic_agent._build_live_context = lambda: ""
        anthropic_agent._fetch_rag_context = AsyncMock(return_value="")
        anthropic_agent._call_llm = AsyncMock(return_value=("hello", None))

        await anthropic_agent.chat("hi")

        assert anthropic_agent._history[0]["content"] == agent_mod._CHAT_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_a_strategy_seeded_session_is_upgraded_to_the_chat_prompt(self, anthropic_agent):
        """Otherwise the assistant answers chat questions as a code generator."""
        anthropic_agent._history.append({"role": "system", "content": agent_mod._SYSTEM_PROMPT})
        anthropic_agent._build_live_context = lambda: ""
        anthropic_agent._fetch_rag_context = AsyncMock(return_value="")
        anthropic_agent._call_llm = AsyncMock(return_value=("hello", None))

        await anthropic_agent.chat("hi")

        assert anthropic_agent._history[0]["content"] == agent_mod._CHAT_SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_the_exchange_is_persisted(self, anthropic_agent):
        anthropic_agent._build_live_context = lambda: ""
        anthropic_agent._fetch_rag_context = AsyncMock(return_value="")
        anthropic_agent._call_llm = AsyncMock(return_value=("hello", None))

        await anthropic_agent.chat("hi")

        assert {"role": "user", "content": "hi"} in list(anthropic_agent._history)
        assert {"role": "assistant", "content": "hello"} in list(anthropic_agent._history)

    @pytest.mark.asyncio
    async def test_context_is_injected_ephemerally_and_not_persisted(self, anthropic_agent):
        """The snapshot is stale the moment it is sent; storing it poisons later turns."""
        anthropic_agent._build_live_context = lambda: "## Live Market Snapshot\n- XAU_USD: 2000"
        anthropic_agent._fetch_rag_context = AsyncMock(return_value="## Market Context (RAG)\nregime A")
        anthropic_agent._call_llm_with_messages = AsyncMock(return_value=("answer", None))

        await anthropic_agent.chat("what is gold doing")

        sent = anthropic_agent._call_llm_with_messages.await_args.args[0]
        assert any("Live Market Snapshot" in m["content"] for m in sent)
        assert any("regime A" in m["content"] for m in sent)
        assert not any("Live Market Snapshot" in m["content"] for m in anthropic_agent._history)

    @pytest.mark.asyncio
    async def test_an_error_becomes_a_readable_sentence_not_a_raise(self, anthropic_agent):
        anthropic_agent._build_live_context = lambda: ""
        anthropic_agent._fetch_rag_context = AsyncMock(return_value="")
        anthropic_agent._call_llm = AsyncMock(return_value=("", "Invalid Anthropic API key"))

        reply = await anthropic_agent.chat("hi")

        assert "unable to respond" in reply
        assert "Invalid Anthropic API key" in reply

    @pytest.mark.asyncio
    async def test_a_failed_exchange_is_not_written_into_history(self, anthropic_agent):
        anthropic_agent._build_live_context = lambda: "## Live Market Snapshot\n- XAU_USD: 2000"
        anthropic_agent._fetch_rag_context = AsyncMock(return_value="")
        anthropic_agent._call_llm_with_messages = AsyncMock(return_value=("", "provider down"))

        await anthropic_agent.chat("hi")

        assert not any(m.get("content") == "hi" for m in anthropic_agent._history)

    @pytest.mark.asyncio
    async def test_history_never_grows_past_its_bound(self, anthropic_agent):
        anthropic_agent._build_live_context = lambda: ""
        anthropic_agent._fetch_rag_context = AsyncMock(return_value="")
        anthropic_agent._call_llm = AsyncMock(return_value=("ok", None))

        for i in range(agent_mod._CHAT_MAX_HISTORY_TURNS + 10):
            await anthropic_agent.chat(f"message {i}")

        assert len(anthropic_agent._history) <= anthropic_agent._history.maxlen


# ── factory ───────────────────────────────────────────────────────────────────


class TestCreateAgent:
    def test_with_no_source_there_is_no_fetcher(self, monkeypatch):
        monkeypatch.setattr(agent_mod, "_LLM_BACKEND", "anthropic", raising=False)

        assert create_agent(api_key="k").candle_fetcher is None

    @pytest.mark.asyncio
    async def test_a_candle_source_becomes_an_async_fetcher(self, monkeypatch):
        monkeypatch.setattr(agent_mod, "_LLM_BACKEND", "anthropic", raising=False)
        source = MagicMock()
        source.get_candles = AsyncMock(return_value=[{"close": 1.0}])

        a = create_agent(candle_source=source, api_key="k")
        candles = await a.candle_fetcher("XAU_USD", "H1", 10)

        assert candles == [{"close": 1.0}]
        source.get_candles.assert_awaited_once_with("XAU_USD", "H1", 10)

    @pytest.mark.asyncio
    async def test_the_deprecated_alias_still_works(self, monkeypatch, caplog):
        monkeypatch.setattr(agent_mod, "_LLM_BACKEND", "anthropic", raising=False)
        source = MagicMock()
        source.get_candles = AsyncMock(return_value=[])

        a = create_agent(oanda_stream=source, api_key="k")

        assert a.candle_fetcher is not None
        assert await a.candle_fetcher("XAU_USD", "H1", 1) == []

    def test_an_explicit_source_wins_over_the_alias(self, monkeypatch):
        monkeypatch.setattr(agent_mod, "_LLM_BACKEND", "anthropic", raising=False)
        wanted, ignored = MagicMock(), MagicMock()
        wanted.get_candles = AsyncMock(return_value=["wanted"])
        ignored.get_candles = AsyncMock(return_value=["ignored"])

        a = create_agent(candle_source=wanted, oanda_stream=ignored, api_key="k")

        assert asyncio.run(a.candle_fetcher("XAU_USD", "H1", 1)) == ["wanted"]

    def test_extra_kwargs_reach_the_agent(self, monkeypatch):
        monkeypatch.setattr(agent_mod, "_LLM_BACKEND", "anthropic", raising=False)

        a = create_agent(api_key="k", max_iterations=7, target_sharpe=2.5)

        assert a.max_iterations == 7
        assert a.target_sharpe == pytest.approx(2.5)
