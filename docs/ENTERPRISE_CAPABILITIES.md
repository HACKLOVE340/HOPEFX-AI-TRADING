# Enterprise capabilities — status

This file replaces `enterprise-requirements.txt`, which used to sit in the repo
root. That file was never a pip requirements file: it was a Markdown wishlist of
**Node.js** packages, and its `.txt` name made every dependency tool treat it as
Python input. `pip install -r enterprise-requirements.txt` failed at line 5
(`1. GraphQL` is not a requirement specifier), and `pip-audit -r` refused to
parse it. Nothing in the repo referenced it.

The list is also entirely superseded — the platform already implements all ten
items. The table below records what the wishlist asked for and what actually
exists, with the file that provides it.

| Wishlist item | Node package it suggested | Status in this repo |
|---|---|---|
| GraphQL | `graphql` | **Present** — `api/graphql_schema.py` (strawberry-graphql). Query, Mutation and WebSocket Subscriptions; per-request JWT auth in the GraphQL context. Gated behind `FEATURE_GRAPHQL_API`. |
| WebSocket | `ws` / `socket.io` | **Present** — `api/ws_live.py`. Do not add a top-level `websocket/` package: it shadows the `websocket-client` library and silently disables the REST fallback in `market_data/mt5_live_feed.py` (audit S13-02a). |
| Load testing | `artillery` | **Present** — `k6/load_tests.js` (smoke, load, soak, spike, stress and breakpoint scenarios, p95/error-rate thresholds, a rate-limit probe and a WebSocket test) with `k6/run_load_test.sh`, plus `locust/load_tests.py` (three weighted user classes, including an authenticated trader placing orders). `tests/unit/test_k6_load_tests.py` validates the k6 config without needing k6 installed. Separately, `scripts/stress_test.py` and `risk/stress_test.py` are *scenario* stress tests — flash crashes, liquidity freezes, portfolio shocks — not HTTP throughput tests. |
| Distributed tracing | `opentracing` / `zipkin` | **Present** — OpenTelemetry, wired in `app.py`; instruments FastAPI, SQLAlchemy and Redis. Spans propagate through `core/event_bus.py`. |
| Feature flagging | `unleash-client` | **Present** — `config/feature_flags.py`: a central registry mapping each feature to an env var, with per-flag maturity defaults. |
| Rate limiting | `express-rate-limit` | **Present** — `rate_limiting/` (Redis sliding window with in-process fallback) plus `DefaultRateLimitMiddleware` in `core/middleware.py`. |
| Security scanning | `snyk` / `npm audit` | **Present** — `bandit` and `detect-secrets` in pre-commit; `pip-audit` for Python dependencies; `npm audit` for `frontend/`, `dashboard/` and `mobile-app/`. |
| Audit logging | `winston` | **Present** — `database/system_events.py` and `infrastructure/logging.py`. |
| Monitoring | `prom-client` | **Present** — `prometheus_client`; see `docs/GRAFANA_SETUP.md`. |
| Chaos engineering | `chaos-monkey` | **Present** — `chaos/` (`ChaosController`, `FaultInjector`) for data-pipeline fault injection. |

## Neither runs in CI

All ten are implemented. The one gap left is wiring: no workflow under
`.github/workflows/` invokes k6 or Locust, so the load tests only run when
someone runs them by hand. For a money-moving system about to go live, "how
many concurrent order placements before latency degrades" is worth having a
recorded answer to, on a schedule.

## Correction

An earlier revision of this file said load testing was **absent**. That was
wrong, and wrong through a bad measurement rather than a judgement call: the
check grepped file *contents* for "k6", "locust" and "artillery" while
restricting itself to `.py`, `.txt`, `.toml` and `.yml`. `k6/load_tests.js` is
JavaScript, and `locust/load_tests.py` names the tool in its path and docstring
but not in a form that search matched. The directories were there the whole
time. Corrected after `tests/unit/test_k6_load_tests.py` turned up in a test
run.
