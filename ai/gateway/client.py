# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The single entry point for every model call.

Routing, timeouts, fall-through, budget and audit live here so that no caller
has to get them right individually. Before this, `api/brain.py` selected a
backend from environment variables, built the request inline, and turned any
failure into a 502 -- no second leg, no ceiling, and no record of what was
spent or which model answered.

Two rules are worth stating because they are easy to get backwards:

* **Budget is checked before the request is issued.** A ceiling enforced after
  the money is spent is a report, not a limit.
* **A refusal is an answer.** Transport failures advance to the next leg;
  guardrail rejections, refusals, budget denials and our own 4xx do not.
  Retrying a guardrail rejection on a second vendor defeats the guardrail, and
  retrying a budget denial defeats the ceiling. `ai.gateway.chain` owns that
  predicate; this module obeys it.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from ai.cache.store import ResponseCache
from ai.gateway import audit, breakers, budget
from ai.gateway.chain import ChainLeg, resolve_chain, should_fall_through
from ai.guardrails.input import screen_input
from ai.guardrails.output import GuardrailViolation, StreamScanner, scan_output, validate_output

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 60.0

#: Decoded ceiling for one image, before base64 expansion.
#:
#: A phone camera hands back a 4K frame. Reading a chart off one costs several
#: times the tokens of a downscaled copy and returns no more detail than the
#: model can use, so the frame is downscaled at the edge and this refuses
#: anything that arrives past the limit anyway. Refused BEFORE dispatch, for the
#: same reason the budget is checked before the request is issued: a ceiling
#: enforced after the money is spent is a report.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

#: What the vision chain's models actually accept. An unlisted type is refused
#: rather than forwarded and rejected by the vendor at cost.
SUPPORTED_IMAGE_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif"},
)


@dataclass(frozen=True)
class ImageRef:
    """One image, base64-encoded, on its way to a vision model.

    Base64 rather than a path or a URL on purpose: a camera frame never touches
    disk (the UI promises exactly that), and a URL would have the vendor fetch
    something this platform has not seen.
    """

    media_type: str
    data_b64: str

    def __post_init__(self) -> None:
        if self.media_type not in SUPPORTED_IMAGE_TYPES:
            raise ValueError(
                f"unsupported image type {self.media_type!r}; expected one of {sorted(SUPPORTED_IMAGE_TYPES)}"
            )
        if not self.data_b64:
            raise ValueError("an image needs data")
        # base64 is 4 characters per 3 bytes; compare decoded size so the limit
        # means what it says.
        approx_bytes = (len(self.data_b64) * 3) // 4
        if approx_bytes > MAX_IMAGE_BYTES:
            raise ValueError(f"image is {approx_bytes} bytes, over the {MAX_IMAGE_BYTES} limit; downscale it first")

    def digest(self) -> str:
        """Content hash, for the cache key. Never the bytes themselves."""
        return hashlib.sha256(self.data_b64.encode("ascii", "ignore")).hexdigest()


class GatewayError(RuntimeError):
    """Base for every gateway failure."""


class BudgetExceeded(GatewayError):
    """A ceiling refused the call before it was issued."""


class NoProviderAvailable(GatewayError):
    """Every leg of the chain failed, or none could be reached."""


class ProviderError(GatewayError):
    """One leg failed. `reason` decides whether the next leg is tried."""

    def __init__(self, reason: str, *, provider: str = "", model: str = "") -> None:
        super().__init__(f"{provider or 'provider'} failed: {reason}")
        self.reason, self.provider, self.model = reason, provider, model


@dataclass(frozen=True)
class ModelRequest:
    role: str = "reasoning"
    prompt: str = ""
    timeout_s: float = DEFAULT_TIMEOUT_S
    estimated_usd: float = 0.0
    #: Opaque fingerprint of the state the question is asked against (open
    #: positions, config, regime). It is part of the cache key: the same prompt
    #: asked under different state is a different question, and an answer
    #: computed under old state must never be served against new state.
    tool_state: str = ""
    #: Images for the `vision` role. Empty for every text call, so the text path
    #: is byte-for-byte what it was.
    images: tuple[ImageRef, ...] = ()

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValueError("a model request needs a prompt")

    def image_fingerprint(self) -> str:
        """A stable digest of the attached images, or "" when there are none.

        Part of the cache key. Without it the key is prompt + model +
        tool_state, so two different camera frames asked "what is this?" hash
        identically and the second is served the FIRST frame's reading — a
        confident answer about an image nobody looked at. That is the same
        class of defect as serving an hour-old market view against new
        positions, which is why `tool_state` exists.
        """
        if not self.images:
            return ""
        return hashlib.sha256("|".join(i.digest() for i in self.images).encode()).hexdigest()


@dataclass(frozen=True)
class ModelResponse:
    text: str
    provider: str
    model: str
    latency_ms: float
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    attempts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    #: True when this answer was served from the response cache. A cached
    #: answer costs nothing and charges nothing; callers that report spend
    #: need to be able to tell the two apart.
    cached: bool = False


class Provider(Protocol):
    """What the gateway needs from a vendor adapter."""

    def complete(self, *, model: str, prompt: str, timeout_s: float) -> Any: ...


class GatewayClient:
    """Routes a request along its role's chain and records what happened."""

    def __init__(
        self,
        providers: dict[str, Provider] | None = None,
        *,
        cache: ResponseCache | None = None,
    ) -> None:
        self._providers = providers if providers is not None else {}
        # Optional by construction: a deployment that wants every call to reach
        # a live model passes no cache, and nothing about routing, budget or
        # audit changes. Caching is an economy, never a correctness dependency.
        # Falls back to the process-wide cache rather than requiring every
        # construction site to pass one. There are five in production, and a
        # per-site wiring step is a step somebody forgets — which is exactly how
        # install_shared_cache came to have zero callers.
        if cache is None:
            from ai.cache.store import shared_cache

            cache = shared_cache()
        self._cache = cache

    @property
    def cache(self) -> ResponseCache | None:
        return self._cache

    def available_providers(self) -> frozenset[str]:
        """Vendors this deployment can actually reach.

        A chain leg whose vendor is absent is SKIPPED rather than counted as a
        failed attempt: a missing credential is a deployment fact, not a
        provider outage, and conflating them would make an unconfigured
        deployment look like a failing one.
        """
        return frozenset(self._providers)

    def call_sync(self, request: ModelRequest, *, operator: str) -> ModelResponse:
        """Issue `request`, falling through the chain as the rules allow."""
        # Input screening happens before anything is spent or sent. A guardrail
        # violation is an ANSWER, not a transport failure: it is raised, never
        # retried on a second vendor, because retrying it would defeat the
        # guardrail. `chain.should_fall_through` encodes the same rule.
        screen_input(request.prompt)

        # A hit is answered before the budget is consulted and before any leg
        # is tried. It costs nothing, so no ceiling may refuse it and
        # `budget.charge` is never reached for a call that was not made.
        # Screening still runs first: a prompt the guardrail rejects must be
        # rejected whether or not something like it was asked before.
        cache_model = self._cache_model(request.role)
        hit = self._cache_lookup(request, cache_model)
        if hit is not None:
            self._audit_cache_hit(request, operator, cache_model)
            return hit

        allowed, reason = budget.check(operator, request.estimated_usd)
        if not allowed:
            # Audited before raising: a refused call is still a call someone
            # made, and the ceiling working is worth being able to show.
            audit.record_call(
                operator=operator,
                role=request.role,
                prompt=request.prompt,
                attempts=[{"provider": None, "reason": "budget_exceeded", "detail": reason}],
                served_by=None,
                model=None,
                latency_ms=0.0,
                cost_usd=0.0,
                tokens_in=0,
                tokens_out=0,
            )
            raise BudgetExceeded(reason)

        attempts: list[dict[str, Any]] = []
        started = time.perf_counter()

        for leg in resolve_chain(request.role):
            provider = self._providers.get(leg.provider)
            if provider is None:
                attempts.append({"provider": leg.provider, "reason": "no_credentials", "skipped": True})
                continue
            # A vendor the breaker has taken out of rotation is skipped without
            # being dialled. Without this a comprehensively dead primary was
            # contacted on every single call and every call paid its timeout
            # before reaching a leg that works.
            if breakers.is_open(leg.provider):
                attempts.append({"provider": leg.provider, "model": leg.model, "reason": "circuit_open"})
                continue
            # A leg that cannot see is SKIPPED, never handed a blind prompt.
            # Dropping the image and asking a text model "what is this?" gets a
            # confident answer about nothing at all, which is far worse than
            # falling through to a leg that can actually look. Mirrors how
            # `embed_sync` treats a vendor with no embeddings API.
            if request.images and not getattr(provider, "supports_images", False):
                attempts.append({"provider": leg.provider, "model": leg.model, "reason": "provider_unavailable"})
                logger.info("ai.gateway: %s cannot accept images; trying the next leg", leg.provider)
                continue
            try:
                kwargs: dict[str, Any] = {
                    "model": leg.model,
                    "prompt": request.prompt,
                    "timeout_s": request.timeout_s,
                }
                if request.images:
                    kwargs["images"] = request.images
                result = provider.complete(**kwargs)
            except ProviderError as exc:
                attempts.append({"provider": leg.provider, "model": leg.model, "reason": exc.reason})
                # Only a transport failure counts against the vendor. A refusal
                # or a 400 means it answered, and marking a working vendor down
                # for a malformed prompt would remove a leg the chain needs.
                breakers.record_outcome(leg.provider, reason=exc.reason)
                if should_fall_through(exc.reason):
                    logger.info("ai.gateway: %s failed (%s); trying the next leg", leg.provider, exc.reason)
                    continue
                self._audit(request, operator, attempts, None, None, started, 0.0, 0, 0)
                raise
            except Exception as exc:  # an adapter bug must not look like a refusal
                attempts.append({"provider": leg.provider, "model": leg.model, "reason": "adapter_error"})
                breakers.record_outcome(leg.provider, reason="adapter_error")
                logger.exception("ai.gateway: adapter raised for %s: %s", leg.provider, exc)
                continue

            # Screen what came back before anything else happens to it.
            #
            # Placed here, after the leg served and before the answer is cached,
            # audited as served, or returned: a credential must not be stored in
            # the response cache, where a later identical prompt would be handed
            # it again without a provider ever being called.
            #
            # A rejection is an ANSWER, not a transport failure -- the same rule
            # the input guardrail follows. `should_fall_through` does not list
            # `guardrail_rejected`, so this correctly does not retry on a second
            # vendor: asking another model the same question is not a fix for
            # the first one having leaked, and would just spend money to leak
            # twice.
            scan_output(str(getattr(result, "text", "")))

            latency_ms = (time.perf_counter() - started) * 1000
            cost = float(getattr(result, "cost_usd", 0.0) or 0.0)
            tokens_in = int(getattr(result, "tokens_in", 0) or 0)
            tokens_out = int(getattr(result, "tokens_out", 0) or 0)
            attempts.append({"provider": leg.provider, "model": leg.model, "reason": "served"})
            breakers.record_outcome(leg.provider, reason=None)
            budget.charge(operator, cost)
            self._audit(request, operator, attempts, leg, leg.model, started, cost, tokens_in, tokens_out)
            served = ModelResponse(
                text=str(getattr(result, "text", "")),
                provider=leg.provider,
                model=leg.model,
                latency_ms=latency_ms,
                cost_usd=cost,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                attempts=tuple(attempts),
            )
            self._cache_store(request, served)
            return served

        self._audit(request, operator, attempts, None, None, started, 0.0, 0, 0)
        tried = ", ".join(f"{a['provider']}={a['reason']}" for a in attempts) or "no legs"
        raise NoProviderAvailable(f"no model served role {request.role!r}: {tried}")

    def stream_sync(
        self,
        request: ModelRequest,
        *,
        operator: str,
        on_complete: Callable[[ModelResponse], None] | None = None,
    ) -> Iterator[str]:
        """Issue `request` and yield the answer as it arrives.

        A generator, not a coroutine. The AI job runner already gives this a
        dedicated worker thread and `ai/jobs/progress.py` already bridges that
        thread to the event loop, so streaming needs an iterator rather than an
        async rewrite of the path that budgets, screens and audits every model
        call. `ai/jobs/runner.py` states the same reasoning from the other side.

        **Every control on `call_sync` runs here too.** A second entry point is
        exactly how a control comes to run for half the traffic, so this shares
        the same helpers rather than reimplementing the sequence: `screen_input`,
        the cache, `budget.check`, the breaker and image-capability skips,
        `StreamScanner` (the streaming form of `scan_output`),
        `breakers.record_outcome`, `budget.charge`, `_audit`, `_cache_store`.

        Three rules exist only here:

        * **A vendor that cannot stream degrades to `complete()`** rather than
          being skipped. Losing a leg because it lacks a nicety would make the
          chain shorter for streamed calls than for buffered ones.
        * **A failure after the first token does not fall through.** The
          operator has already read part of one vendor's answer; continuing it
          with another splices two opinions into one.
        * **Cancellation still charges and still audits.** The tokens were
          generated whether or not anyone read them, so `finally` — not the
          success path — owns both. A cancel that costs nothing is a way to
          spend money the ceiling cannot see.

        `on_complete` receives the finished `ModelResponse` — which vendor
        served, what it cost, how long it took. A generator can only yield text,
        and the caller needs the rest to report the job's result; a callback is
        explicit about that where reaching into the client afterwards would be
        guesswork that silently returns nothing when it is wrong.
        """
        screen_input(request.prompt)

        cache_model = self._cache_model(request.role)
        hit = self._cache_lookup(request, cache_model)
        if hit is not None:
            self._audit_cache_hit(request, operator, cache_model)
            # One piece. A cached answer has no arrival to follow, and pretending
            # otherwise by re-chunking it would be theatre.
            if on_complete is not None:
                on_complete(hit)
            yield hit.text
            return

        allowed, reason = budget.check(operator, request.estimated_usd)
        if not allowed:
            audit.record_call(
                operator=operator,
                role=request.role,
                prompt=request.prompt,
                attempts=[{"provider": None, "reason": "budget_exceeded", "detail": reason}],
                served_by=None,
                model=None,
                latency_ms=0.0,
                cost_usd=0.0,
                tokens_in=0,
                tokens_out=0,
            )
            raise BudgetExceeded(reason)

        attempts: list[dict[str, Any]] = []
        started = time.perf_counter()

        for leg in resolve_chain(request.role):
            provider = self._providers.get(leg.provider)
            if provider is None:
                attempts.append({"provider": leg.provider, "reason": "no_credentials", "skipped": True})
                continue
            if breakers.is_open(leg.provider):
                attempts.append({"provider": leg.provider, "model": leg.model, "reason": "circuit_open"})
                continue
            if request.images and not getattr(provider, "supports_images", False):
                attempts.append({"provider": leg.provider, "model": leg.model, "reason": "provider_unavailable"})
                logger.info("ai.gateway: %s cannot accept images; trying the next leg", leg.provider)
                continue

            served, fell_through = yield from self._stream_one_leg(
                request, operator, provider, leg, attempts, started, on_complete
            )
            if served:
                return
            if not fell_through:
                # The leg failed in a way that must not be retried elsewhere —
                # it had already spoken, or it refused. `_stream_one_leg` has
                # raised in those cases, so reaching here means a hard stop.
                return

        self._audit(request, operator, attempts, None, None, started, 0.0, 0, 0)
        tried = ", ".join(f"{a['provider']}={a['reason']}" for a in attempts) or "no legs"
        raise NoProviderAvailable(f"no model served role {request.role!r}: {tried}")

    def _stream_one_leg(
        self,
        request: ModelRequest,
        operator: str,
        provider: Any,
        leg: ChainLeg,
        attempts: list[dict[str, Any]],
        started: float,
        on_complete: Callable[[ModelResponse], None] | None = None,
    ) -> Any:
        """Run one leg. Yields text; returns (served, may_fall_through).

        Split out so `stream_sync` reads as the control sequence it is, and so
        the `finally` that charges and audits a cancelled stream has a single
        home rather than being repeated per exit.
        """
        scanner = StreamScanner()
        tokens_in = tokens_out = 0
        spoke = False
        completed = False
        charged = False
        # The buffered path's adapter already priced the call; the streaming
        # path has only token counts, so the cost is computed from the same
        # table rather than a second one.
        known_cost: float | None = None
        final_text = ""

        def _settle(reason: str) -> None:
            """Record what happened, once, whatever the exit was.

            Called from `finally`, so a stream abandoned by its consumer — a
            closed panel, a cancelled job — is charged and audited exactly like
            one that ran to the end. `GeneratorExit` does not reach the success
            path, which is why this cannot live there.

            **An abandoned stream usually has no reported usage.** Every wire
            format here sends token counts in a final frame, so a stream cut off
            part-way reports zero — while the vendor generated and billed for
            real tokens. Charging that zero would make cancellation a way to
            spend money the ceiling cannot see, so an unmeasured partial is
            charged at the request's own estimate instead. That follows the rule
            `estimate_cost` already states for an unpriced model: under-counting
            spend is the failure mode that matters, over-counting only refuses a
            later call early.

            **This is per LEG, where `call_sync` audits per request.** That is
            deliberate rather than incidental: a leg only reaches here if it
            produced billable tokens, so a leg that failed before saying
            anything still adds no record. A leg that streamed half an answer
            and then died did real, billed work, and a request that falls
            through after that has genuinely paid two vendors — one record each
            is what makes that legible.
            """
            nonlocal charged
            if charged:
                return
            charged = True
            cost = known_cost if known_cost is not None else self._stream_cost(leg, tokens_in, tokens_out)
            if cost <= 0.0 and reason == "partial":
                cost = float(request.estimated_usd or 0.0)
            attempts.append({"provider": leg.provider, "model": leg.model, "reason": reason})
            budget.charge(operator, cost)
            self._audit(request, operator, attempts, leg, leg.model, started, cost, tokens_in, tokens_out)

        try:
            if getattr(provider, "supports_streaming", False):
                kwargs: dict[str, Any] = {
                    "model": leg.model,
                    "prompt": request.prompt,
                    "timeout_s": request.timeout_s,
                }
                if request.images:
                    kwargs["images"] = request.images
                for chunk in provider.stream(**kwargs):
                    tokens_in += int(getattr(chunk, "tokens_in", 0) or 0)
                    tokens_out += int(getattr(chunk, "tokens_out", 0) or 0)
                    text = str(getattr(chunk, "text", "") or "")
                    if not text:
                        continue
                    # Raises GuardrailViolation, which is an ANSWER: it
                    # propagates rather than falling through to another vendor.
                    released = scanner.feed(text)
                    if released:
                        spoke = True
                        yield released
                tail = scanner.finish()
                if tail:
                    spoke = True
                    yield tail
                final_text = scanner.text
            else:
                # Degrade, do not skip. The whole answer in one piece is still
                # an answer, and it keeps the chain the same length for both.
                result = provider.complete(model=leg.model, prompt=request.prompt, timeout_s=request.timeout_s)
                text = str(getattr(result, "text", ""))
                scan_output(text)
                tokens_in = int(getattr(result, "tokens_in", 0) or 0)
                tokens_out = int(getattr(result, "tokens_out", 0) or 0)
                known_cost = float(getattr(result, "cost_usd", 0.0) or 0.0)
                final_text = text
                spoke = bool(text)
                yield text
            completed = True
        except ProviderError as exc:
            breakers.record_outcome(leg.provider, reason=exc.reason)
            if spoke:
                # Already partway through this vendor's answer. Continuing it
                # with a different model would splice two opinions and present
                # them as one, which is worse than an error.
                attempts.append({"provider": leg.provider, "model": leg.model, "reason": exc.reason})
                logger.warning(
                    "ai.gateway: %s failed %d characters into a stream; not falling through",
                    leg.provider,
                    len(scanner.text),
                )
                raise
            attempts.append({"provider": leg.provider, "model": leg.model, "reason": exc.reason})
            if should_fall_through(exc.reason):
                logger.info("ai.gateway: %s failed (%s); trying the next leg", leg.provider, exc.reason)
                return False, True
            raise
        except GuardrailViolation:
            # Never retried on a second vendor: asking another model the same
            # question is not a fix for the first one having leaked.
            attempts.append({"provider": leg.provider, "model": leg.model, "reason": "guardrail_rejected"})
            raise
        except Exception as exc:  # an adapter bug must not look like a refusal
            breakers.record_outcome(leg.provider, reason="adapter_error")
            attempts.append({"provider": leg.provider, "model": leg.model, "reason": "adapter_error"})
            logger.exception("ai.gateway: adapter raised while streaming from %s: %s", leg.provider, exc)
            if spoke:
                raise
            return False, True
        finally:
            if completed:
                breakers.record_outcome(leg.provider, reason=None)
                _settle("served")
            elif spoke or tokens_out:
                # Abandoned, or failed after generating tokens. Either way the
                # vendor did work somebody has to pay for and compliance has to
                # be able to see.
                _settle("partial")

        if completed:
            # Only a whole answer is cached. A partial one would be served
            # complete to the next identical prompt.
            response = ModelResponse(
                text=final_text,
                provider=leg.provider,
                model=leg.model,
                latency_ms=(time.perf_counter() - started) * 1000,
                cost_usd=(known_cost if known_cost is not None else self._stream_cost(leg, tokens_in, tokens_out)),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                attempts=tuple(attempts),
            )
            self._cache_store(request, response)
            if on_complete is not None:
                on_complete(response)
        return completed, False

    def embed_sync(self, texts: list[str], *, operator: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> Any:
        """Embed `texts` along the `embedding` chain, under the same controls.

        Embeddings were the one model call with no ceiling and no record:
        `api/brain.py` picked a backend inline, fell back to OpenAI or Ollama
        with a hand-written `if`, and left no trace of what it cost. They are a
        model call, so they go through the same door.

        A vendor with no embeddings API raises `provider_unavailable`, which
        falls through -- the chain reaches one that can embed instead of failing
        the request, which is what that inline `if` was approximating.
        """
        if not texts:
            raise ValueError("embedding needs at least one text")

        # Screened for the same reason a completion is: these texts are stored,
        # and an injected instruction in a stored vector is a delayed prompt.
        for text in texts:
            screen_input(text)

        allowed, reason = budget.check(operator, 0.0)
        if not allowed:
            raise BudgetExceeded(reason)

        attempts: list[dict[str, Any]] = []
        started = time.perf_counter()
        fingerprint = "\n".join(texts)

        for leg in resolve_chain("embedding"):
            provider = self._providers.get(leg.provider)
            if provider is None:
                attempts.append({"provider": leg.provider, "reason": "no_credentials", "skipped": True})
                continue
            embed = getattr(provider, "embed", None)
            if embed is None:
                attempts.append({"provider": leg.provider, "reason": "provider_unavailable"})
                continue
            try:
                result = embed(model=leg.model, texts=texts, timeout_s=timeout_s)
            except ProviderError as exc:
                attempts.append({"provider": leg.provider, "model": leg.model, "reason": exc.reason})
                if should_fall_through(exc.reason):
                    continue
                self._audit_embedding(fingerprint, operator, attempts, None, None, started, 0.0, 0)
                raise
            except Exception as exc:
                attempts.append({"provider": leg.provider, "model": leg.model, "reason": "adapter_error"})
                logger.exception("ai.gateway: embedding adapter raised for %s: %s", leg.provider, exc)
                continue

            cost = float(getattr(result, "cost_usd", 0.0) or 0.0)
            tokens_in = int(getattr(result, "tokens_in", 0) or 0)
            attempts.append({"provider": leg.provider, "model": leg.model, "reason": "served"})
            budget.charge(operator, cost)
            self._audit_embedding(fingerprint, operator, attempts, leg, leg.model, started, cost, tokens_in)
            return result

        self._audit_embedding(fingerprint, operator, attempts, None, None, started, 0.0, 0)
        tried = ", ".join(f"{a['provider']}={a['reason']}" for a in attempts) or "no legs"
        raise NoProviderAvailable(f"no model served role 'embedding': {tried}")

    def _audit_embedding(
        self,
        fingerprint: str,
        operator: str,
        attempts: list[dict[str, Any]],
        leg: ChainLeg | None,
        model: str | None,
        started: float,
        cost: float,
        tokens_in: int,
    ) -> None:
        audit.record_call(
            operator=operator,
            role="embedding",
            prompt=fingerprint,
            attempts=attempts,
            served_by=leg.provider if leg else None,
            model=model,
            latency_ms=(time.perf_counter() - started) * 1000,
            cost_usd=cost,
            tokens_in=tokens_in,
            tokens_out=0,
        )

    def call_structured(
        self,
        request: ModelRequest,
        *,
        operator: str,
        required: dict[str, tuple[type, ...]] | None = None,
        ranges: dict[str, tuple[float, float]] | None = None,
    ) -> dict[str, Any]:
        """Issue `request` and validate the response before any caller sees it.

        Validation is not coercion: a response the model did not produce in the
        requested shape raises GuardrailViolation, and the caller's fallback to
        a deterministic answer is the safe result. The gateway does NOT retry a
        validation failure on the next leg -- the model answered, it just did
        not answer in the contract.
        """
        response = self.call_sync(request, operator=operator)
        return validate_output(response.text, required=required, ranges=ranges)

    # -- cache -----------------------------------------------------------------

    @staticmethod
    def _stream_cost(leg: ChainLeg, tokens_in: int, tokens_out: int) -> float:
        """Price a streamed call from the same table the adapters use.

        A stream reports usage and not a price, so the cost has to be computed
        here. Imported lazily because `ai.gateway.adapters` imports this module
        — and deliberately reused rather than reimplemented: a second pricing
        table is a second place for a streamed call to be charged differently
        from a buffered one.
        """
        from ai.gateway.adapters import estimate_cost

        return estimate_cost(leg.model, tokens_in=tokens_in, tokens_out=tokens_out, provider=leg.provider)

    def _cache_model(self, role: str) -> str:
        """The model a lookup is keyed on: the first leg this deployment can reach.

        Not simply the chain head -- a leg whose vendor has no credentials is
        skipped at dispatch, so keying on it would key every entry on a model
        that never answers. When a reachable leg fails at runtime and a later
        leg serves, the answer is stored under the model that actually served,
        so the next lookup misses. That is a lost economy, never a wrong answer:
        an answer is only ever served under the identity that produced it.
        """
        for leg in resolve_chain(role):
            if leg.provider in self._providers:
                return leg.model
        return ""

    @staticmethod
    def _cache_state(request: ModelRequest) -> str:
        """The state an answer is bound to: declared tool state PLUS the images.

        The cache's own rule is that a request declaring no `tool_state` is not
        cached at all -- silence means do not cache. That rule is preserved
        exactly: an image request that declares no tool state still returns ""
        here and is still not cached. What this adds is that when a request IS
        cacheable, two different images can never share a key.
        """
        fingerprint = request.image_fingerprint()
        if not fingerprint:
            return request.tool_state
        if not request.tool_state:
            # Still uncacheable, by the module's existing policy. Returning the
            # fingerprint alone here would quietly start caching image calls
            # that never opted in.
            return ""
        return f"{request.tool_state}|img:{fingerprint}"

    def _cache_lookup(self, request: ModelRequest, cache_model: str) -> ModelResponse | None:
        if self._cache is None or not cache_model:
            return None
        try:
            hit = self._cache.get(
                prompt=request.prompt,
                model=cache_model,
                tool_state=self._cache_state(request),
            )
        except Exception:  # a cache fault must never fail a call
            logger.exception("ai.gateway: cache lookup failed; treating as a miss")
            return None
        if not isinstance(hit, ModelResponse):
            return None
        # Reported as free and as cached. A cached answer that still reported
        # its original cost would double-count spend in every operator report.
        return replace(
            hit,
            cost_usd=0.0,
            cached=True,
            attempts=({"provider": hit.provider, "model": hit.model, "reason": "cache_hit"},),
        )

    def _cache_store(self, request: ModelRequest, response: ModelResponse) -> None:
        """Store a served answer. Only a served answer ever gets here."""
        if self._cache is None or not response.text:
            return
        try:
            self._cache.put(
                prompt=request.prompt,
                model=response.model,
                tool_state=self._cache_state(request),
                value=response,
            )
        except Exception:  # a cache fault must never fail a call
            logger.exception("ai.gateway: cache store failed; the answer still stands")

    def _audit_cache_hit(self, request: ModelRequest, operator: str, model: str) -> None:
        """A hit is still a call somebody made, and it is recorded as one."""
        audit.record_call(
            operator=operator,
            role=request.role,
            prompt=request.prompt,
            attempts=[{"provider": "cache", "model": model, "reason": "cache_hit"}],
            served_by="cache",
            model=model,
            latency_ms=0.0,
            cost_usd=0.0,
            tokens_in=0,
            tokens_out=0,
        )

    def _audit(
        self,
        request: ModelRequest,
        operator: str,
        attempts: list[dict[str, Any]],
        leg: ChainLeg | None,
        model: str | None,
        started: float,
        cost: float,
        tokens_in: int,
        tokens_out: int,
    ) -> None:
        audit.record_call(
            operator=operator,
            role=request.role,
            prompt=request.prompt,
            attempts=attempts,
            served_by=leg.provider if leg else None,
            model=model,
            latency_ms=(time.perf_counter() - started) * 1000,
            cost_usd=cost,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "BudgetExceeded",
    "GatewayClient",
    "MAX_IMAGE_BYTES",
    "SUPPORTED_IMAGE_TYPES",
    "GatewayError",
    "ImageRef",
    "ModelRequest",
    "ModelResponse",
    "NoProviderAvailable",
    "Provider",
    "ProviderError",
]
