# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/brain.py
============
AI Strategy Generator endpoints.

Routes
------
POST /api/brain/generate-strategy  — prompt → generated strategy code + backtest
POST /api/brain/deploy-strategy    — deploy generated strategy to paper trading
POST /api/brain/chat               — free-form chat with the trading assistant
"""

from __future__ import annotations

import logging
import asyncio
import os
from datetime import datetime, timezone as _tz

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import TokenPayload, get_current_user, require_role
from core.ai_quota import ai_quota

from strategies.strategy_execution_boundary import ExecutionScope

logger = logging.getLogger(__name__)


def _activation_scope() -> ExecutionScope:
    """The scope this deployment actually activates at.

    Derived from BROKER_TYPE rather than defaulted. The gate this feeds
    (`StrategyExecutionBoundary`) previously took `ExecutionScope.RESEARCH` as
    its default and short-circuited every check on it, so activation happened
    under a scope no caller had chosen. Choosing here means the claim matches
    what the registry then does -- it sets StrategyState.ACTIVE either way.
    """
    return ExecutionScope.PAPER if os.getenv("BROKER_TYPE", "paper").strip().lower() == "paper" else ExecutionScope.LIVE


router = APIRouter(prefix="/api/brain", tags=["AI Brain"])

# Small epsilon to prevent division by zero in RSI calculation when avg_loss == 0
_RSI_EPSILON = 1e-9


# ── Helpers ───────────────────────────────────────────────────────────────────


def _detect_llm_backend() -> tuple[str | None, str | None]:
    """
    Auto-detect the configured LLM backend from environment variables.

    Returns (backend, api_key) where backend is "anthropic" | "openai" | None.
    Explicit LLM_BACKEND env var takes precedence; otherwise whichever key is set.
    """
    explicit = os.getenv("LLM_BACKEND", "").lower()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")

    if explicit == "anthropic" and anthropic_key:
        return "anthropic", anthropic_key
    if explicit == "openai" and openai_key:
        return "openai", openai_key

    # Auto-detect: prefer Anthropic when both are set
    if anthropic_key:
        return "anthropic", anthropic_key
    if openai_key:
        return "openai", openai_key

    return None, None


_NO_BACKEND_DETAIL = "No LLM backend configured. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or OLLAMA_BASE_URL."


def _configured_primary():
    """The operator-configured primary leg, or None when unset/unreadable.

    Never fatal: a config-store problem must degrade to the environment
    defaults below, not take the LLM endpoints down.
    """
    try:
        from ai.gateway.chain import resolve_chain

        return resolve_chain("reasoning")[0]
    except Exception as exc:  # a settings read must not break inference
        logger.debug("brain: could not resolve the configured model chain: %s", exc)
        return None


def _detect_llm_runtime() -> tuple[str | None, str | None]:
    """Return (backend, model) for the raw-LLM endpoints below.

    This is the display/config-safe counterpart to ``_detect_llm_backend()``,
    which returns (backend, api_key). The two were conflated once — health,
    complete and embed unpacked the tuple as (backend, model), which sent the
    raw API key to the browser as the "model" field and passed it as the model
    name on OpenAI calls. Never return a secret from this function.

    Ollama is a fallback for local deployments: used only when neither cloud
    key is set but OLLAMA_BASE_URL is configured.
    """
    backend, _api_key = _detect_llm_backend()

    # The superadmin's configured primary wins when it names the backend we
    # actually have credentials for. Before this, Platform Configuration's
    # provider/model fields were written to the config store and read by
    # nothing -- an operator could set them, save, and change nothing (D8).
    # `_detect_llm_backend` stays as the credential-driven bootstrap: it decides
    # which backend is *reachable*, and the chain decides which model on it.
    configured = _configured_primary()
    if configured is not None and configured.provider == backend:
        return backend, configured.model

    if backend == "anthropic":
        return "anthropic", os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    if backend == "openai":
        return "openai", os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    if os.getenv("OLLAMA_BASE_URL"):
        return "ollama", os.getenv("OLLAMA_MODEL", "llama3")
    return None, None


# ── Models ────────────────────────────────────────────────────────────────────


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=5, max_length=2000)
    symbol: str = Field("XAU_USD")
    timeframe: str = Field("H1")
    candle_count: int = Field(500, ge=100, le=2000)


class BacktestSummary(BaseModel):
    total_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int


class GenerateResponse(BaseModel):
    success: bool
    strategy_name: str
    strategy_code: str
    backtest: BacktestSummary | None
    iterations: int
    error: str | None = None


class DeployRequest(BaseModel):
    strategy_name: str
    strategy_code: str
    symbol: str = "XAU_USD"
    timeframe: str = "H1"
    mode: str = "paper"


class DeployResponse(BaseModel):
    success: bool
    message: str
    strategy_id: str | None = None
    status: str | None = None
    validation_errors: list[str] | None = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    reply: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/generate-strategy", response_model=GenerateResponse)
async def generate_strategy(
    req: GenerateRequest,
    user: TokenPayload = Depends(require_role("admin")),
) -> GenerateResponse:
    """
    Generate a trading strategy from a plain-English prompt.

    Uses brain.llm_agent.LLMAgent; supports both ANTHROPIC_API_KEY and
    OPENAI_API_KEY (auto-detected via LLM_BACKEND env var, Anthropic preferred).
    Requires: role >= 'admin' (LLM calls cost money per invocation).
    """
    backend, api_key = _detect_llm_backend()

    if not backend:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "LLM backend not configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY to enable AI strategy generation."
            ),
        )

    try:
        from brain.llm_agent import LLMAgent

        agent = LLMAgent(api_key=api_key, backend=backend)
        result = await agent.generate_strategy(
            prompt=req.prompt,
            symbol=req.symbol,
            timeframe=req.timeframe,
            candle_count=req.candle_count,
        )

        bt = None
        if result.backtest and result.backtest.error is None:
            bt = BacktestSummary(
                total_return_pct=round(result.backtest.total_return * 100, 4),
                sharpe_ratio=round(result.backtest.sharpe, 4),
                max_drawdown_pct=round(result.backtest.max_drawdown * 100, 4),
                win_rate=round(result.backtest.win_rate, 4),
                total_trades=result.backtest.trades,
            )

        response = GenerateResponse(
            success=result.success,
            strategy_name=result.strategy_name,
            strategy_code=result.strategy_code,
            backtest=bt,
            iterations=result.iterations,
            error=result.error,
        )

        # Persist to strategy history if generation succeeded
        if result.success and result.strategy_name:
            try:
                import uuid as _uuid
                from datetime import datetime as _dt, timezone as _tz

                strategies = _load_strategies(user.sub)
                strategies.append(
                    {
                        "strategy_id": f"ai_{_uuid.uuid4().hex[:8]}",
                        "strategy_name": result.strategy_name,
                        "symbol": req.symbol,
                        "timeframe": req.timeframe,
                        "created_at": _dt.now(_tz.utc).isoformat(),
                        "status": "draft",
                        "backtest": bt.model_dump() if bt else None,
                        "strategy_code": result.strategy_code,
                    }
                )
                _save_strategies(user.sub, strategies[-50:])  # keep last 50
            except Exception as _save_exc:
                logger.debug("strategy history save: %s", _save_exc)

        return response
    except Exception as exc:
        logger.warning("LLM agent error: %s", exc, exc_info=True)
        return GenerateResponse(
            success=False,
            strategy_name="",
            strategy_code="",
            backtest=None,
            iterations=0,
            error="Strategy generation failed — check server logs",
        )


@router.post("/deploy-strategy", response_model=DeployResponse)
async def deploy_strategy(
    req: DeployRequest,
    user: TokenPayload = Depends(require_role("admin")),
) -> DeployResponse:
    """
    Deploy a generated strategy to paper/live trading.

    Registers the strategy source with the DynamicStrategyRegistry — which
    AST-safety-validates and compiles it in an isolated namespace — and then
    activates it so it is actually available for live signal generation. This
    performs a real, verifiable deployment: on success the returned
    ``strategy_id`` is the registry version_id and the strategy is ACTIVE.

    If validation/compilation fails, an HONEST ``success=False`` response is
    returned with the validation errors — never a false "deployed" claim.

    Requires: role >= 'admin' (deploys to live trading infrastructure).
    """
    if not req.strategy_code.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="strategy_code is empty",
        )

    try:
        from strategies.dynamic_registry import get_dynamic_registry
    except Exception as exc:
        # Registry unavailable — do NOT claim a deployment happened.
        logger.warning("Deploy: dynamic registry import failed: %s", exc, exc_info=True)
        return DeployResponse(
            success=False,
            message="Deployment infrastructure unavailable — strategy was NOT deployed. Check server logs.",
            status="unavailable",
        )

    registry = get_dynamic_registry()

    # Phase 1: register (AST safety validation + isolated compilation).
    try:
        version_id = await registry.register_strategy(
            name=req.strategy_name,
            source_code=req.strategy_code,
            symbol=req.symbol,
            timeframe=req.timeframe,
            author_id=user.sub,
        )
    except ValueError as verr:
        # Validation/compilation rejected the strategy — return an honest failure
        # rather than pretending it deployed.
        logger.info("Deploy: strategy '%s' rejected by registry: %s", req.strategy_name, verr)
        return DeployResponse(
            success=False,
            message=f"Strategy '{req.strategy_name}' failed validation and was NOT deployed.",
            status="validation_failed",
            validation_errors=[str(verr)],
        )
    except Exception as exc:
        logger.warning("Deploy: registration error: %s", exc, exc_info=True)
        return DeployResponse(
            success=False,
            message="Deploy failed during registration — strategy was NOT deployed. Check server logs.",
            status="error",
        )

    # Phase 2: activate (atomic swap into the live active strategy set).
    try:
        await registry.activate_strategy(scope=_activation_scope(), version_id=version_id)
    except Exception as exc:
        # Registered/validated but activation failed — be honest about the
        # partial state instead of reporting a successful deploy.
        logger.warning("Deploy: activation error for %s: %s", version_id, exc, exc_info=True)
        return DeployResponse(
            success=False,
            message=(
                f"Strategy '{req.strategy_name}' validated and registered but activation FAILED — "
                "it is NOT live. Check server logs."
            ),
            strategy_id=version_id,
            status="validated_not_activated",
        )

    logger.info("Deployed AI strategy %s (version %s) to %s mode", req.strategy_name, version_id, req.mode)
    return DeployResponse(
        success=True,
        message=f"Strategy '{req.strategy_name}' deployed and activated for {req.mode} trading.",
        strategy_id=version_id,
        status="active",
    )


def _keyless_chat_reply(message: str) -> str:
    """Rule-based assistant used when no LLM backend (ANTHROPIC/OPENAI) is set.

    Keeps the chat usable offline: recognises common intents and points the user
    at the right part of the platform instead of returning a 503 error.
    """
    m = message.lower().strip()

    def has(*words: str) -> bool:
        return any(w in m for w in words)

    note = (
        "\n\n_(Offline assistant — set `ANTHROPIC_API_KEY` (Claude) or "
        "`OPENAI_API_KEY` in your `.env` to unlock the full conversational AI.)_"
    )

    if has("hello", "hi ", "hey", "good morning", "good afternoon") or m in {"hi", "hey"}:
        return (
            "Hi — I'm the HOPEFX assistant. Ask me about your account, open positions, signals, risk, or how to use the platform."
            + note
        )
    if has("help", "what can you", "how do i", "commands"):
        return (
            "I can point you to:\n"
            "• **Account / balance** → Dashboard → Account panel\n"
            "• **Open positions** → Positions page\n"
            "• **Live signals** → Signals page\n"
            "• **Gold price / chart** → Markets → XAUUSD\n"
            "• **Risk & kill-switch** → Risk page\n"
            "• **Economic events** → Calendar page\n"
            "• **AI strategies** → Brain → Generate Strategy" + note
        )
    if has("account", "balance", "equity", "margin", "p&l", "pnl", "profit"):
        return (
            "Your live account balance, equity, margin and P&L are on the **Dashboard → Account** panel, refreshed in real time."
            + note
        )
    if has("position", "open trade", "my trades"):
        return (
            "Open positions, entry price, size and unrealised P&L are on the **Positions** page. Use the Risk page to manage exposure."
            + note
        )
    if has("signal", "entry", "setup"):
        return "Active ML trade signals (direction, confidence, entry/stop/target) are on the **Signals** page." + note
    if has("price", "gold", "xau", "quote", "market"):
        return (
            "Live XAUUSD price and candles are on **Markets → XAUUSD**. Note: only the keyless gold feed is active unless you configure broker/feed API keys."
            + note
        )
    if has("risk", "kill switch", "drawdown", "stop"):
        return (
            "Risk limits, drawdown, VaR/CVaR and the kill switch are on the **Risk** page. The kill switch halts all new orders immediately."
            + note
        )
    if has("strategy", "backtest"):
        return (
            "Generate and backtest AI strategies under **Brain → Generate Strategy**. Full strategy generation needs an LLM key (see below)."
            + note
        )
    if has("news", "event", "calendar", "fomc", "nfp", "cpi"):
        return "Upcoming high-impact events (FOMC, NFP, jobless claims) are on the **Calendar** page." + note
    return (
        "I'm running in offline mode, so I can't reason freely yet — but I can help you find your "
        "account, positions, signals, market data, risk controls, or the calendar. Ask about any of those." + note
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user: TokenPayload = Depends(ai_quota(feature="chat")),
) -> ChatResponse:
    """
    Free-form chat with the HOPEFX AI trading assistant.

    Maintains per-process conversation history (LLMAgent is module-level
    singleton per worker).  Requires role >= 'starter'.  When no LLM backend is
    configured, falls back to a rule-based offline assistant instead of erroring.
    """
    backend, api_key = _detect_llm_backend()

    if not backend:
        return ChatResponse(reply=_keyless_chat_reply(req.message))

    try:
        from brain.llm_agent import LLMAgent

        # Module-level singleton so conversation history persists across requests
        # within the same worker process.
        global _chat_agent
        if "_chat_agent" not in globals() or _chat_agent is None:
            _chat_agent = LLMAgent(api_key=api_key, backend=backend)

        reply = await _chat_agent.chat(req.message)
        return ChatResponse(reply=reply)
    except Exception as exc:
        # LLM backend errored (bad key, timeout, rate limit). Degrade to the
        # offline assistant so the user still gets a useful response.
        logger.warning("Chat agent error: %s — falling back to offline assistant", exc, exc_info=True)
        return ChatResponse(reply=_keyless_chat_reply(req.message))


_chat_agent: object | None = None


# ── Strategy history & management ─────────────────────────────────────────────
# Persisted via api.db_store so strategies survive restarts.

_STRAT_KEY = "brain:strategies:{uid}"


def _load_strategies(user_id: str) -> list[dict]:
    from api.db_store import db_get

    stored = db_get(_STRAT_KEY.format(uid=user_id))
    if stored and isinstance(stored, list):
        return stored
    return []


def _save_strategies(user_id: str, strategies: list[dict]) -> None:
    from api.db_store import db_set

    db_set(_STRAT_KEY.format(uid=user_id), strategies)


@router.get("/strategies", summary="List AI-generated strategies")
async def list_strategies(
    limit: int = 20,
    user: TokenPayload = Depends(require_role("starter")),
) -> dict:
    """Return the user's AI-generated strategy history."""
    strategies = _load_strategies(user.sub)
    return {"strategies": strategies[-limit:], "total": len(strategies)}


@router.get("/strategies/{strategy_id}", summary="Get a specific AI strategy")
async def get_strategy(
    strategy_id: str,
    user: TokenPayload = Depends(require_role("starter")),
) -> dict:
    strategies = _load_strategies(user.sub)
    for s in strategies:
        if s.get("strategy_id") == strategy_id:
            return s
    raise HTTPException(status_code=404, detail="Strategy not found")


@router.delete("/strategies/{strategy_id}", summary="Delete an AI strategy")
async def delete_strategy(
    strategy_id: str,
    user: TokenPayload = Depends(require_role("starter")),
) -> dict:
    strategies = _load_strategies(user.sub)
    updated = [s for s in strategies if s.get("strategy_id") != strategy_id]
    if len(updated) == len(strategies):
        raise HTTPException(status_code=404, detail="Strategy not found")
    _save_strategies(user.sub, updated)
    return {"ok": True, "strategy_id": strategy_id}


@router.post("/strategies/{strategy_id}/backtest", summary="Re-run backtest on a strategy")
async def backtest_strategy(
    strategy_id: str,
    user: TokenPayload = Depends(require_role("starter")),
) -> dict:
    strategies = _load_strategies(user.sub)
    for s in strategies:
        if s.get("strategy_id") == strategy_id:
            # Return existing backtest results or trigger a new run
            return {
                "strategy_id": strategy_id,
                "backtest": s.get("backtest"),
                "status": "completed" if s.get("backtest") else "no_backtest",
            }
    raise HTTPException(status_code=404, detail="Strategy not found")


@router.post("/strategies/{strategy_id}/activate", summary="Activate a strategy for paper trading")
async def activate_strategy(
    strategy_id: str,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    strategies = _load_strategies(user.sub)
    for s in strategies:
        if s.get("strategy_id") == strategy_id:
            s["status"] = "active"
            _save_strategies(user.sub, strategies)
            return {"ok": True, "strategy_id": strategy_id, "status": "active"}
    raise HTTPException(status_code=404, detail="Strategy not found")


@router.post("/strategies/{strategy_id}/deactivate", summary="Deactivate a strategy")
async def deactivate_strategy(
    strategy_id: str,
    user: TokenPayload = Depends(require_role("admin")),
) -> dict:
    strategies = _load_strategies(user.sub)
    for s in strategies:
        if s.get("strategy_id") == strategy_id:
            s["status"] = "inactive"
            _save_strategies(user.sub, strategies)
            return {"ok": True, "strategy_id": strategy_id, "status": "inactive"}
    raise HTTPException(status_code=404, detail="Strategy not found")


# ── LLM extension endpoints ───────────────────────────────────────────────────
# These endpoints expose the raw LLM backend (health probe, completion, and
# embedding) for components that need direct LLM access beyond the structured
# generate-strategy / chat flows above.


@router.get("/health", summary="LLM backend health probe")
async def brain_health(
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Return the detected LLM backend and whether it is reachable.

    Response never contains credentials — ``model`` is the model name only.
    Probe failures return generic detail strings for the same reason.
    """
    backend, model = _detect_llm_runtime()
    available = backend is not None
    detail: str | None = None

    if backend == "anthropic":
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": os.getenv("ANTHROPIC_API_KEY", ""),
                        "anthropic-version": "2023-06-01",
                    },
                )
            available = r.status_code == 200
            if not available:
                detail = f"Anthropic API returned HTTP {r.status_code}."
        except Exception:
            available = False
            detail = "Anthropic API unreachable."
    elif backend == "openai":
        try:
            import openai

            await asyncio.to_thread(openai.models.list)  # lightweight probe
        except Exception:
            available = False
            detail = "OpenAI API unreachable."
    elif backend == "ollama":
        try:
            import httpx

            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}/api/tags")
            available = r.status_code == 200
        except Exception:
            available = False
            detail = "Ollama server unreachable."
    else:
        detail = _NO_BACKEND_DETAIL

    return {
        "available": available,
        "backend": backend,
        "model": model,
        "detail": detail,
    }


class CompleteRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=32_000)
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    system: str | None = Field(default=None, max_length=4096)


class CompleteResponse(BaseModel):
    text: str
    backend: str | None
    model: str | None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@router.post("/complete", response_model=CompleteResponse, summary="Raw LLM completion")
async def brain_complete(
    body: CompleteRequest,
    user: TokenPayload = Depends(ai_quota(feature="chat")),
) -> CompleteResponse:
    """Send a raw prompt to the configured LLM backend and return the completion."""
    backend, model = _detect_llm_runtime()

    if backend == "anthropic":
        try:
            import httpx

            payload: dict = {
                "model": model,
                "max_tokens": body.max_tokens,
                "temperature": body.temperature,
                "messages": [{"role": "user", "content": body.prompt}],
            }
            if body.system:
                payload["system"] = body.system
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": os.getenv("ANTHROPIC_API_KEY", ""),
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                )
            r.raise_for_status()
            data = r.json()
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            usage = data.get("usage", {})
            return CompleteResponse(
                text=text,
                backend="anthropic",
                model=model,
                prompt_tokens=usage.get("input_tokens"),
                completion_tokens=usage.get("output_tokens"),
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail="LLM backend error.") from exc

    if backend == "openai":
        try:
            import openai

            messages = []
            if body.system:
                messages.append({"role": "system", "content": body.system})
            messages.append({"role": "user", "content": body.prompt})
            resp = await asyncio.to_thread(
                openai.chat.completions.create,
                model=model or "gpt-4o-mini",
                messages=messages,
                max_tokens=body.max_tokens,
                temperature=body.temperature,
            )
            return CompleteResponse(
                text=resp.choices[0].message.content or "",
                backend="openai",
                model=model,
                prompt_tokens=resp.usage.prompt_tokens if resp.usage else None,
                completion_tokens=resp.usage.completion_tokens if resp.usage else None,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail="LLM backend error.") from exc

    if backend == "ollama":
        try:
            import httpx

            base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            payload = {"model": model, "prompt": body.prompt, "stream": False}
            if body.system:
                payload["system"] = body.system
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(f"{base}/api/generate", json=payload)
            r.raise_for_status()
            data = r.json()
            return CompleteResponse(
                text=data.get("response", ""),
                backend="ollama",
                model=model,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail="LLM backend error.") from exc

    raise HTTPException(status_code=503, detail=_NO_BACKEND_DETAIL)


class EmbedRequest(BaseModel):
    input: str | list[str] = Field(..., description="Text or list of texts to embed.")


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    backend: str | None
    model: str | None
    dimensions: int


@router.post("/embed", response_model=EmbedResponse, summary="Generate text embeddings")
async def brain_embed(
    body: EmbedRequest,
    user: TokenPayload = Depends(ai_quota(feature="chat")),
) -> EmbedResponse:
    """Generate embeddings for one or more texts using the configured LLM backend.

    Anthropic has no embeddings API, so when it is the primary backend the
    request falls through to OpenAI (if OPENAI_API_KEY is also set) or Ollama.
    """
    texts = [body.input] if isinstance(body.input, str) else body.input
    backend, model = _detect_llm_runtime()

    if backend == "anthropic":
        if os.getenv("OPENAI_API_KEY"):
            backend = "openai"
        elif os.getenv("OLLAMA_BASE_URL"):
            backend, model = "ollama", os.getenv("OLLAMA_MODEL", "llama3")
        else:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Anthropic has no embeddings API — set OPENAI_API_KEY or OLLAMA_BASE_URL to enable embeddings."
                ),
            )

    if backend == "openai":
        try:
            import openai

            embed_model = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
            resp = await asyncio.to_thread(openai.embeddings.create, model=embed_model, input=texts)
            vectors = [item.embedding for item in resp.data]
            return EmbedResponse(
                embeddings=vectors,
                backend="openai",
                model=embed_model,
                dimensions=len(vectors[0]) if vectors else 0,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail="LLM embed error.") from exc

    if backend == "ollama":
        try:
            import httpx

            base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            embed_model = os.getenv("OLLAMA_EMBED_MODEL", model or "nomic-embed-text")
            vectors = []
            async with httpx.AsyncClient(timeout=30.0) as client:
                for text in texts:
                    r = await client.post(
                        f"{base}/api/embeddings",
                        json={"model": embed_model, "prompt": text},
                    )
                    r.raise_for_status()
                    vectors.append(r.json().get("embedding", []))
            return EmbedResponse(
                embeddings=vectors,
                backend="ollama",
                model=embed_model,
                dimensions=len(vectors[0]) if vectors else 0,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail="LLM embed error.") from exc

    raise HTTPException(status_code=503, detail=_NO_BACKEND_DETAIL)


# ── Market Analysis & Insights ────────────────────────────────────────────────


@router.get("/status", summary="AI Brain system status")
async def brain_status(
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Return overall AI brain system status including LLM backend availability."""
    backend, model = _detect_llm_backend()
    strategy_count = len(_load_strategies(user.sub))
    return {
        "llm_available": backend is not None,
        "backend": backend,
        "model": model,
        "strategies_saved": strategy_count,
        "features": {
            "generate_strategy": backend is not None,
            "market_analysis": True,
            "insights": True,
            "chat": backend is not None,
            "embeddings": backend == "openai",
        },
    }


class AnalyzeRequest(BaseModel):
    symbol: str = Field("XAU_USD")
    timeframe: str = Field("H1")
    candle_count: int = Field(200, ge=50, le=2000)
    indicators: list[str] = Field(default_factory=list)


@router.post("/analyze", summary="Run AI analysis on a symbol/timeframe")
async def analyze_market(
    req: AnalyzeRequest,
    user: TokenPayload = Depends(ai_quota(feature="chat")),
) -> dict:
    """
    Fetch recent OHLCV data and return structured market analysis:
    trend, momentum, key support/resistance levels, and a directional signal.
    Uses live price data when available via the nuclear streamer.
    """
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    try:
        from core.app_state import app_state

        nuclear = getattr(app_state, "nuclear_streamer", None)
        if nuclear and hasattr(nuclear, "get_ohlcv"):
            candles = nuclear.get_ohlcv(req.symbol, req.timeframe, req.candle_count)
            closes = [float(c["close"]) for c in candles if "close" in c]
            highs = [float(c["high"]) for c in candles if "high" in c]
            lows = [float(c["low"]) for c in candles if "low" in c]
    except Exception as exc:
        logger.debug("analyze_market data fetch: %s", exc)

    if len(closes) < 20:
        return {
            "symbol": req.symbol,
            "timeframe": req.timeframe,
            "status": "insufficient_data",
            "message": "Connect a live data feed to enable AI market analysis.",
        }

    n = len(closes)
    sma20 = sum(closes[-20:]) / 20
    sma50 = sum(closes[-50:]) / 50 if n >= 50 else None
    current = closes[-1]

    # RSI-14
    gains, losses = [], []
    for i in range(max(1, n - 15), n):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / len(gains) if gains else 0
    avg_loss = sum(losses) / len(losses) if losses else _RSI_EPSILON
    rsi = 100 - (100 / (1 + avg_gain / avg_loss))

    # ATR-14
    atr_vals = []
    for i in range(max(1, n - 14), n):
        tr = max(
            highs[i] - lows[i] if (highs and lows) else 0,
            abs(highs[i] - closes[i - 1]) if highs else 0,
            abs(lows[i] - closes[i - 1]) if lows else 0,
        )
        atr_vals.append(tr)
    atr = sum(atr_vals) / len(atr_vals) if atr_vals else 0

    trend = "bullish" if current > sma20 else "bearish"
    if sma50 is not None:
        if current > sma20 > sma50:
            trend = "strong_bullish"
        elif current < sma20 < sma50:
            trend = "strong_bearish"

    momentum = "overbought" if rsi > 70 else ("oversold" if rsi < 30 else "neutral")
    resistance = max(highs[-20:]) if highs else round(current * 1.005, 2)
    support = min(lows[-20:]) if lows else round(current * 0.995, 2)

    if trend.endswith("bullish") and momentum != "overbought":
        signal = "BUY"
    elif trend.endswith("bearish") and momentum != "oversold":
        signal = "SELL"
    else:
        signal = "NEUTRAL"

    return {
        "symbol": req.symbol,
        "timeframe": req.timeframe,
        "current_price": round(current, 5),
        "trend": trend,
        "momentum": momentum,
        "signal": signal,
        "indicators": {
            "sma_20": round(sma20, 5),
            "sma_50": round(sma50, 5) if sma50 is not None else None,
            "rsi_14": round(rsi, 2),
            "atr_14": round(atr, 5),
        },
        "key_levels": {
            "resistance": round(resistance, 5),
            "support": round(support, 5),
        },
        "bars_analyzed": n,
    }


@router.get("/market-analysis", summary="Current market analysis for XAU/USD")
async def get_market_analysis(
    symbol: str = "XAU_USD",
    timeframe: str = "H1",
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """Return the latest market analysis for the requested symbol/timeframe."""
    return await analyze_market(
        AnalyzeRequest(symbol=symbol, timeframe=timeframe, candle_count=200),
        user=user,
    )


_INSIGHTS_KEY = "brain:insights:{uid}"


@router.get("/insights", summary="AI-generated trading insights")
async def get_insights(
    user: TokenPayload = Depends(get_current_user),
) -> dict:
    """
    Return AI-generated insights based on the user's strategy history and
    recent market conditions. Results are cached for 5 minutes per user.
    """
    from api.db_store import db_get, db_set

    cached = db_get(_INSIGHTS_KEY.format(uid=user.sub))
    if cached and isinstance(cached, dict):
        ts = cached.get("generated_at", "")
        try:
            stored_dt = datetime.fromisoformat(ts)
            # Ensure timezone-aware comparison
            if stored_dt.tzinfo is None:
                stored_dt = stored_dt.replace(tzinfo=_tz.utc)
            age_s = (datetime.now(_tz.utc) - stored_dt).total_seconds()
            if age_s < 300:
                return cached
        except Exception:  # nosec B110  # noqa: S110
            pass

    strategies = _load_strategies(user.sub)
    backend, _ = _detect_llm_backend()
    insights: list[dict] = []

    if strategies:
        recent = strategies[-10:]
        winning = [s for s in recent if s.get("backtest") and s["backtest"].get("total_return_pct", 0) > 0]
        win_rate = len(winning) / len(recent) if recent else 0

        if win_rate >= 0.6:
            insights.append(
                {
                    "type": "performance",
                    "severity": "positive",
                    "title": "Strong Strategy Win Rate",
                    "message": f"{round(win_rate * 100)}% of your recent strategies are profitable.",
                    "action": "Consider deploying your best-performing strategy.",
                }
            )
        elif win_rate < 0.4:
            insights.append(
                {
                    "type": "performance",
                    "severity": "warning",
                    "title": "Low Strategy Win Rate",
                    "message": f"Only {round(win_rate * 100)}% of recent strategies are profitable.",
                    "action": "Review your prompts — try adding risk management constraints.",
                }
            )

        dd_vals = [abs(s["backtest"].get("max_drawdown_pct", 0)) for s in recent if s.get("backtest")]
        if dd_vals:
            avg_dd = sum(dd_vals) / len(dd_vals)
            if avg_dd > 15:
                insights.append(
                    {
                        "type": "risk",
                        "severity": "warning",
                        "title": "High Average Drawdown",
                        "message": f"Average max drawdown across recent strategies: {round(avg_dd, 1)}%.",
                        "action": "Add 'max_drawdown < 10%' constraints to your strategy prompts.",
                    }
                )

    try:
        analysis = await get_market_analysis(user=user)
        signal = analysis.get("signal", "NEUTRAL")
        trend = analysis.get("trend", "unknown")
        rsi = analysis.get("indicators", {}).get("rsi_14")
        if signal != "NEUTRAL":
            insights.append(
                {
                    "type": "market",
                    "severity": "info",
                    "title": f"XAU/USD Market Signal: {signal}",
                    "message": f"Current trend is {trend.replace('_', ' ')}."
                    + (f" RSI at {round(rsi, 1)}." if rsi else ""),
                    "action": f"Consider generating a {signal.lower()} strategy for XAU/USD H1.",
                }
            )
    except Exception as exc:
        logger.debug("insights market analysis: %s", exc)

    if not insights:
        insights.append(
            {
                "type": "onboarding",
                "severity": "info",
                "title": "Get Started",
                "message": "Generate your first AI strategy using the strategy generator.",
                "action": "Click 'Generate Strategy' and describe your trading idea.",
            }
        )

    result = {
        "insights": insights,
        "total": len(insights),
        "generated_at": datetime.now(_tz.utc).isoformat(),
        "llm_enhanced": backend is not None,
    }
    db_set(_INSIGHTS_KEY.format(uid=user.sub), result)
    return result
