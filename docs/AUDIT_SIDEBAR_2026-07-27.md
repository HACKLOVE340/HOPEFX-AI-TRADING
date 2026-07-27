# Full sidebar audit — measured, 2026-07-27

Follow-up to the seven-AI-page audit, widened to the **entire sidebar**: all 8
sections and 57 pages in `frontend/src/components/sidebar/navConfig.ts`.

Method, same as before — nothing guessed. Each page's import graph was traced to
its API calls (546 unique endpoints across the sidebar). The real backend was
booted in-process and **269 concrete GET endpoints were probed authenticated as
superadmin**. Anomalies were then read at the source to separate real bugs from
probe artifacts.

## Sections and pages covered

| Section | Pages |
|---|---|
| Overview | Dashboard, Live Feed, Trade, Portfolio, Watchlist, Economic Calendar, AI Assistant, Price Alerts, System Status, Documentation |
| Trading | AI Chart Bot, AI Chart Dashboard, Terminal, Nuclear AI |
| Tools | Trade Journal, Prop Firm, Copy Trading, Risk Calculator, Strategy Builder |
| Analytics | AI Intelligence, Performance, P&L, Transparency, News, AI Strategy, Correlation, Indicators, Pattern Detector, Walk-Forward, A/B Testing, TCA, Geopolitical, Research, Replay |
| Community | Leaderboard, Signal Feed, Marketplace, Affiliate, Teams, Chat |
| Account | Profile, Wallet, Notifications, KYC, Academy, Mobile, Sub-Accounts, Elite, Upgrade, Settings |
| Admin | Admin Panel, Audit Log, Security Ops, Auto-Heal, Observability, ML-Ops, Whitelabel |
| Super Admin | Master Control, Reliability |

## Headline: 260 of 269 probed endpoints return 200

The nine non-200s break down as follows.

### Real bugs — fixed this pass

1. **`GET /api/calendar/today` → 500 on every request.** (Pages: Trade,
   Portfolio, Economic Calendar, Terminal.) `get_today()` called the
   `get_upcoming()` *endpoint function* directly, so the unsupplied `importance`
   parameter kept its raw `Query(None)` marker object. `Query(None)` is truthy,
   so the code entered the filter branch and called `.lower()` on a `Query`
   object: `AttributeError: 'Query' object has no attribute 'lower'`.
   `get_high_impact()` had the same latent fault. Both now delegate to a
   plain-value helper `_upcoming_events()`; the decorated endpoints are never
   called directly.

2. **`GET /api/notifications` → bare 404.** (Pages: Dashboard, Live Feed, Trade,
   Portfolio — the notification bell polls this everywhere.) The route resolves
   only *with* a trailing slash under the app's custom router registration, and
   the SPA catch-all (`core/page_routes.py`) returns a bare `Response(404)` for
   any unmatched `/api/*` path — which pre-empts Starlette's automatic
   trailing-slash redirect. The client calls the bare path, so it 404'd. The
   list endpoint is now registered at both `""` and `"/"`.

3. **`GET /api/superadmin/audit/export` → silently empty CSV.** (Page: Audit
   Log — found by a static sweep for the same anti-pattern, not the probe.)
   `export_audit_log()` called `get_audit_log(page=1, limit=500, user=user)`,
   omitting `user_id` and `event_type`, which stayed as `Query(None)` markers.
   Truthy, so the query filtered by marker objects; the surrounding try/except
   swallowed the resulting error and returned an empty event list, so the
   export produced a CSV with only a header. Now passes `user_id=None,
   event_type=None` explicitly.

   The same static sweep cleared the two other export endpoints that call their
   list endpoint directly — `compliance/audit-trail/export` and `logs/export`
   both already pass every filter explicitly (`action=None`, `search=None`).

### Correct behaviour — not bugs

4–5. **`/api/superadmin/nuclear/status` and `/log` → 403.** (Pages: Admin,
   Master Control.) "Superadmin nuclear operations require 2FA verification."
   This is the intended security gate — the probe's token had no TOTP step.
   Working as designed.

6–7. **`/api/trading/ohlcv/XAUUSD` and `/api/risk/live-price/XAUUSD` → 503.**
   (Pages: Live Feed, Trade, Risk Calculator.) The no-market-feed condition
   documented in AUDIT_2026-07-27.md — needs `TWELVE_API_KEY`. Both degrade
   gracefully: OHLCV returns a structured "data unavailable" state, and the Risk
   Calculator wraps its poll in `try/catch` and falls back to store prices with
   an "Enter manually" message. No page breaks.

### Probe artifacts — not reproducible in the real app

8. **`/api/trading/patterns` → 422 "symbol required".** The real caller
   (`tradingApi.patterns(symbol, …)`) always sends `?symbol=`; the probe
   couldn't reconstruct the axios `params` object and called it bare.

9. **`/api/monetization/marketplace/strategies/XAUUSD` → 404 "Strategy not
   found".** The probe substituted the symbol `XAUUSD` for a strategy id. A 404
   for a nonexistent strategy is correct; real callers pass real ids.

(Also seen and dismissed: `/api/pricing/compare` 422 — the client always passes
`tier_a`/`tier_b`; the probe omitted them.)

## Frontend defect fixed

**Sidebar labels clipped mid-word.** `AI Chart Dashboard`, `Copy Trading`,
`Nuclear AI` and other long labels were hard-cut by `white-space: nowrap;
overflow: hidden` with no ellipsis, at every viewport width (the prod screenshot
audit flagged this too). Added `text-overflow: ellipsis` and a `title` tooltip
so the full label is recoverable on hover. `tsc --noEmit` clean, 26/26 component
tests pass.

## Requires a decision from you — not changed

**Legal-page contact emails point at two domains, neither the live one.** The
site runs on `hopefx.site`, but the pages use `support@hopefx.io` (×5),
`privacy@hopefx.io` (×4) and `legal@hopefx.ai` (×3) — inconsistent across Terms,
Privacy and Pricing. On Terms and Risk Disclosure an undeliverable contact
address is a compliance issue. I did **not** rewrite these: pointing a legal
contact at a domain you may not receive mail on is worse than a known
inconsistency. **Tell me which domain receives mail and I'll standardise all
three in one pass.**

## Verification

- Backend: `tests/unit/test_calendar_notifications_routes.py` (5 new tests,
  all fail on the pre-fix code) + existing notification/brain suites — 27 passed.
- Frontend: `tsc --noEmit` clean; full `vitest` suite 1134/1134; component
  tests 26/26.
- `ruff check` + `ruff format` clean on every touched file.

## Still open (unchanged from prior audits)

1. **`TWELVE_API_KEY`** — the one config change that unblocks every chart and
   live-price surface. Highest-value action on the platform.
2. **`ANTHROPIC_API_KEY`** — AI Strategy, AI Assistant, brain endpoints.
3. Startup gate holds all data pages at 503 for ~2 minutes after any restart;
   pages judged "not responding" in that window are simply mid-boot.
4. The delisted-ticker maps still hardcoded in ~10 non-serving paths
   (research/training scripts) — lower priority, listed in AUDIT_2026-07-27.md.
