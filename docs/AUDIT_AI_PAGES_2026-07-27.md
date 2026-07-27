# AI pages — deep audit, measured, 2026-07-27

Scope: the seven AI pages the user reported as "not responding" — AI Chart Bot,
AI Chart Dashboard, Terminal, Nuclear AI, AI Intelligence, AI Strategy,
AI Assistant.

Method: this is not a code-reading audit. The real backend was booted
in-process (FastAPI TestClient, full lifespan, superadmin login, CSRF), and
**every endpoint those seven pages call — 48 of them, mapped by tracing each
page's import graph — was requested and measured.** Both WebSockets were
exercised with the exact client handshake. The frontend was typechecked and its
full test suite run.

Verdicts below distinguish **measured facts** from the two things this sandbox
cannot measure (outbound internet and a real market feed).

---

## Headline verdicts

| Page | Verdict | Root cause of user-visible failure |
|---|---|---|
| /ai-chart (Chart Bot) | REST layer healthy (18/18 endpoints 200 after gate) | Charts empty until a real feed exists: intraday gold needs `TWELVE_API_KEY` (see AUDIT_2026-07-27.md); daily/weekly gold works from CSV |
| /ai-chart-dashboard | Same as above — same feature module | Same |
| /terminal | All 40+ endpoints respond | LLM widgets dead without an LLM key (was: dead **even with** a key — fixed, see Bug 1) |
| /nuclear | **Fully working**, measured end-to-end | `/ws/nuclear` streams `nuclear_chart_update` frames even in the sandbox. If blank in prod: user's token not reaching the WS — else it works |
| /intelligence | All 14 endpoints 200 | Nothing broken server-side; empty states are honest (no signals generated yet without a feed) |
| /ai-strategy | Generate = 503 without `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` | Configuration, not code — and the health widget was lying about it (Bugs 1–2, fixed) |
| /ai-assistant | **Working** — chat answers via offline fallback with a clear hint | Becomes a real AI with `ANTHROPIC_API_KEY` set |

The frontend is **not** the problem: `tsc --noEmit` clean, 1134/1134 unit tests
pass, every route lazy-loads a real component, the axios client has a 30s
timeout and login already retries 503s.

---

## Bugs found and fixed in this pass

### 1. `api/brain.py` unpacked (backend, **api_key**) as (backend, **model**) — key leak + dead endpoints

`_detect_llm_backend()` returns `(backend, api_key)`. Three endpoints unpacked
it as `(backend, model)`:

- **`GET /api/brain/health` returned the raw ANTHROPIC/OPENAI API key to the
  browser** in the `"model"` field. Any authenticated user could read it.
- **`POST /api/brain/complete` passed the API key as the OpenAI model name** —
  the call failed 502 on every request, for every backend, always. This
  endpoint has never worked.
- With `ANTHROPIC_API_KEY` set (the platform's primary backend — chat and
  generate-strategy both use it via LLMAgent), `complete`/`embed` matched no
  branch and 503'd "No LLM backend configured" **even though it was
  configured.** health simultaneously said `available: true` with detail "No
  LLM backend configured". The /terminal and /ai-strategy widgets consuming
  these could not render a coherent state — this is the measured mechanism
  behind "I configured it and the page still doesn't respond."
- The `"ollama"` branches were unreachable (`_detect_llm_backend` never
  returns ollama).

How it slipped through: the existing unit tests mocked
`_detect_llm_backend → ("openai", "gpt-4")` — the test author *also* believed
the second element was a model.

Fixed: new `_detect_llm_runtime() → (backend, model)` (never secrets), a real
Anthropic branch for `complete` (same httpx pattern LLMAgent uses), an honest
Anthropic probe for `health`, ollama reachable as local fallback, and
`embed` falls through Anthropic→OpenAI/Ollama or 503s accurately ("Anthropic
has no embeddings API"). 9 regression tests in
`tests/unit/test_brain_llm_runtime.py`, all of which fail on the old code —
including one asserting the key never appears anywhere in the health response.

### 2. Blocking LLM calls froze the whole server

`/brain/complete` and `/brain/embed` made **synchronous** `httpx.post`
(timeout 120s) and `openai.*` calls inside `async def`. One user generating a
completion blocked the event loop — every page, every user, up to two
minutes. This is a literal, mechanical "the app stops responding" cause.
Fixed: `httpx.AsyncClient` / `asyncio.to_thread` throughout.

### 3. Login dead for ~18s after every restart

`POST /api/auth/login` → 503 "Auth service not initialised"
(`auth/router.py:325`) until the auth component starts. The component registry
starts components in registration order once deps are met, and `auth_service`
(required, deps=database only) was registered **after** a dozen slow optional
components (news router, feeds, scanners, DOM…). Measured ~18s of failing
logins after boot; on a slow VPS restart, worse. Fixed: `auth_service` now
registers directly after `database`. The frontend's existing 24s login retry
now covers the whole window instead of racing it.

### 4. `/api/chat/status` advertised a model with no backend

`ready: false` but `model: "gpt-4o"` — the assistant page showed a model name
that cannot answer. Now `model: null` when no backend is configured.

---

## Measured facts worth keeping

- **Startup gate**: every data endpoint (all seven pages) returns 503
  `{"status": "starting"}` until `app_state.initialized` — measured 119s in
  the sandbox. Auth, health, billing, superadmin are exempt. After a deploy,
  the app *looks* down for ~2 minutes; TanStack Query's polling recovers the
  pages once the gate opens. Anyone judging "pages not responding" must first
  ask *when since the last restart* they looked.
- **`/ws/live` contract verified end-to-end**: connect → `connected` →
  `auth` (Bearer prefix handled) → `auth_ok` → `subscribe` → `subscribed`.
  Channel names and message types match on both sides for all 12 channels
  (`prices`/`price_tick`, `microstructure`, `volume_delta`,
  `sentiment_update`, `risk_update`, `pattern_detected`, `level_update`,
  `equity_update`, `news_item`, `signal`). No frames flow only because no feed
  produces data in the sandbox — the transport is sound.
- **`/ws/nuclear` streams data**: auth then continuous
  `nuclear_chart_update` frames, measured here. The Nuclear page's backend is
  the healthiest of the seven.
- Slow endpoints under a dead feed: `levels`, `trendlines`, `patterns`,
  `regime`, `ai-analysis` each took 4–5s (internal OHLCV fetch with its own
  timeout); OHLCV itself burned 5–11s before 503ing. The chart page fires ~10
  of these concurrently on mount. With a working feed these are fast; without
  one they make the page feel hung for the first ten seconds.

## What is NOT a code bug — production actions, ranked

1. **Set `TWELVE_API_KEY`** (free tier covers XAU/USD, already wired in
   `config/multi_source_feed.yaml`). Without it there is **no intraday gold
   data source at all** — the flagship chart cannot draw 1m–4h candles no
   matter what code changes. Single highest-value action on the platform.
2. **Set `ANTHROPIC_API_KEY`** — turns on: AI Strategy generation, real AI
   Assistant chat, brain complete/embed (now actually functional with it),
   and LLM widgets on /terminal.
3. Deploy `d88e418` (tick-writer fix) if not already live, then re-run the
   authenticated page sweep from AUDIT_2026-07-26.md.

## Still open (candidates for next pass)

- Importing `app` triggers background feed activity before startup proper —
  observed feed circuit logs during a pure route-dump import. Harmless-looking
  but it slows boot and muddies diagnostics; worth isolating.
- yfinance retry loops eat 60–70s per cycle when Yahoo is unreachable;
  startup and feed threads crawl. A circuit breaker exists — verify its
  thresholds are aggressive enough on the VPS.
- The five REST-only WS channels (`volume_delta`, `sentiment`, `patterns`,
  `levels`, `equity`) only broadcast when the orchestrator produces snapshots;
  charts otherwise rely on REST polling. Fine, but the duplication deserves a
  decision eventually.
