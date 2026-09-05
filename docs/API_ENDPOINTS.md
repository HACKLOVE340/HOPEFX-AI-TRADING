# HOPEFX AI Trading API

**Version:** 1.0.0

Production REST API for the HOPEFX AI Trading platform.

Generated from the registered routers by
`scripts/api_documentation_generator.py` — edit that script, not this file.
Run it after adding or moving an endpoint; `--check` fails when this file and
the routers disagree.

The **Auth** column is a static read, not a live probe. `JWT` means the route
is gated by one of the three mechanisms this codebase uses: a `fastapi.security`
scheme in its dependency tree, a dependency that parses the `Authorization`
header itself (the self-healer, antivirus and `auth/` routers all do), or a
guard called inside the handler body. A route that accepts an optional token
and then decides for itself still shows `JWT`.

`None` means none of the three was found. Some of those are deliberate — health
probes, login and registration, public market data, and the payment and
TradingView webhooks, which are authenticated by HMAC signature instead — so
read a surprising `None` as a question, not a verdict.

Routes are listed under **default** feature flags. Two groups are omitted: the
`/api/v1/*` alias layer, which mirrors every path below, and routes marked
`include_in_schema=False` — compat aliases such as `POST /api/trading/order`
(the documented one is `/api/trading/orders`) and the server-rendered pages.
They are excluded from the OpenAPI schema for the same reason.

## Endpoints

| Method | Path | Auth | Summary | Tags |
|--------|------|------|---------|------|
| `GET` | `/api/2fa/backup-codes` | JWT |  | Two-Factor Auth |
| `POST` | `/api/2fa/backup-codes/regenerate` | JWT |  | Two-Factor Auth |
| `POST` | `/api/2fa/disable` | JWT |  | Two-Factor Auth |
| `POST` | `/api/2fa/setup` | JWT |  | Two-Factor Auth |
| `GET` | `/api/2fa/status` | JWT |  | Two-Factor Auth |
| `POST` | `/api/2fa/verify` | JWT |  | Two-Factor Auth |
| `GET` | `/api/accounts/sub-accounts` | JWT |  | Accounts |
| `POST` | `/api/accounts/sub-accounts` | JWT |  | Accounts |
| `GET` | `/api/accounts/sub-accounts/{account_id}` | JWT | Get a specific sub-account | Accounts |
| `PATCH` | `/api/accounts/sub-accounts/{account_id}` | JWT |  | Accounts |
| `DELETE` | `/api/accounts/sub-accounts/{account_id}` | JWT |  | Accounts |
| `POST` | `/api/accounts/sub-accounts/{account_id}/transfer` | JWT | Transfer balance between sub-accounts | Accounts |
| `GET` | `/api/accounts/teams` | JWT |  | Accounts |
| `POST` | `/api/accounts/teams` | JWT |  | Accounts |
| `POST` | `/api/accounts/teams/{team_id}/members` | JWT |  | Accounts |
| `PATCH` | `/api/accounts/teams/{team_id}/members/{member_id}` | JWT |  | Accounts |
| `DELETE` | `/api/accounts/teams/{team_id}/members/{member_id}` | JWT |  | Accounts |
| `GET` | `/api/admin/` | JWT |  | Admin |
| `GET` | `/api/admin/activity` | JWT |  | Admin |
| `GET` | `/api/admin/alerts` | JWT | Active admin alerts | Admin |
| `GET` | `/api/admin/audit-log` | JWT | Paginated audit log | Admin |
| `GET` | `/api/admin/audit-log/export` | JWT | Export audit log as CSV | Admin |
| `POST` | `/api/admin/backup/trigger` | JWT | Trigger a system backup | Admin |
| `POST` | `/api/admin/broadcast` | JWT | Broadcast a platform-wide message to all users | Admin |
| `GET` | `/api/admin/dashboard-data` | JWT |  | Admin |
| `GET` | `/api/admin/feature-flags` | JWT |  | Platform, Platform |
| `POST` | `/api/admin/feature-flags/{flag_name}/disable` | JWT |  | Platform, Platform |
| `POST` | `/api/admin/feature-flags/{flag_name}/enable` | JWT |  | Platform, Platform |
| `POST` | `/api/admin/feature-flags/{flag_name}/override` | JWT |  | Platform, Platform |
| `POST` | `/api/admin/kill-switch/global` | JWT |  | Settings Extended, Settings Extended |
| `POST` | `/api/admin/kyc/decide` | JWT |  | Admin |
| `GET` | `/api/admin/kyc/pending` | JWT |  | Admin |
| `GET` | `/api/admin/kyc/{user_id}` | JWT |  | Admin |
| `GET` | `/api/admin/logs` | JWT |  | Admin |
| `GET` | `/api/admin/maintenance` | JWT | Get maintenance mode status | Admin |
| `POST` | `/api/admin/maintenance` | JWT | Toggle maintenance mode | Admin |
| `GET` | `/api/admin/monitoring` | JWT |  | Admin |
| `GET` | `/api/admin/overview` | JWT | Admin overview KPIs | Admin |
| `POST` | `/api/admin/pause` | JWT | Pause all automated trading | Admin |
| `POST` | `/api/admin/resume` | JWT | Resume automated trading | Admin |
| `POST` | `/api/admin/risk-settings` | JWT | Update live risk management parameters | Admin |
| `GET` | `/api/admin/settings` | JWT |  | Admin |
| `POST` | `/api/admin/settings` | JWT |  | Admin |
| `GET` | `/api/admin/settings-data` | JWT |  | Admin |
| `POST` | `/api/admin/settings-data` | JWT |  | Admin |
| `GET` | `/api/admin/settings-page` | JWT |  | Admin |
| `GET` | `/api/admin/settings/performance` | JWT | Live system performance metrics | Settings Extended, Settings Extended |
| `GET` | `/api/admin/settings/system` | JWT | Get system-level admin settings | Admin |
| `POST` | `/api/admin/settings/system` | JWT | Update system-level admin settings | Admin |
| `POST` | `/api/admin/settings/test-smtp` | JWT | Send a test email to verify SMTP configuration | Admin |
| `GET` | `/api/admin/status` | JWT | Active admin alerts (alias for /alerts used by frontend adminApi) | Admin |
| `GET` | `/api/admin/strategies` | JWT |  | Admin |
| `GET` | `/api/admin/system-info` | JWT | Server version and uptime | Admin |
| `GET` | `/api/admin/system-metrics` | JWT | System resource metrics | Admin |
| `GET` | `/api/admin/users` | JWT | List all platform users | Admin |
| `GET` | `/api/admin/users/{user_id}` | JWT | Get a specific user | Admin |
| `PATCH` | `/api/admin/users/{user_id}` | JWT | Update a user's role or status | Admin |
| `POST` | `/api/admin/users/{user_id}/ban` | JWT | Ban a user | Admin |
| `POST` | `/api/admin/users/{user_id}/impersonate` | JWT |  | Platform, Platform |
| `POST` | `/api/admin/users/{user_id}/reset-password` | JWT | Trigger password reset email | Admin |
| `GET` | `/api/admin/users/{user_id}/trades` | JWT |  | Platform, Platform |
| `POST` | `/api/admin/users/{user_id}/unban` | JWT | Unban a user | Admin |
| `GET` | `/api/advanced/ab-tests` | JWT |  | Advanced Trading |
| `POST` | `/api/advanced/ab-tests/run` | JWT |  | Advanced Trading |
| `GET` | `/api/advanced/ab-tests/{test_id}` | JWT |  | Advanced Trading |
| `GET` | `/api/advanced/correlation` | JWT |  | Advanced Trading |
| `GET` | `/api/advanced/cot-sentiment` | JWT |  | Advanced Trading |
| `GET` | `/api/alerts/` | JWT |  | Alerts |
| `POST` | `/api/alerts/` | JWT |  | Alerts |
| `GET` | `/api/alerts/active` | JWT |  | Alerts |
| `GET` | `/api/alerts/history/triggers` | JWT |  | Alerts |
| `GET` | `/api/alerts/{alert_id}` | JWT |  | Alerts |
| `DELETE` | `/api/alerts/{alert_id}` | JWT |  | Alerts |
| `POST` | `/api/alerts/{alert_id}/pause` | JWT |  | Alerts |
| `POST` | `/api/alerts/{alert_id}/resume` | JWT |  | Alerts |
| `GET` | `/api/analysis/correlation` | JWT |  | Analysis |
| `GET` | `/api/analysis/cot` | JWT |  | Analysis |
| `POST` | `/api/auth/2fa/confirm` | JWT |  | Authentication |
| `POST` | `/api/auth/2fa/disable` | JWT |  | Authentication |
| `POST` | `/api/auth/2fa/setup` | JWT |  | Authentication |
| `DELETE` | `/api/auth/account` | JWT | Delete authenticated user account | Settings |
| `POST` | `/api/auth/activate-free-tier` | None |  | Authentication |
| `POST` | `/api/auth/change-password` | JWT | Change authenticated user password | Settings |
| `GET` | `/api/auth/csrf-token` | None |  | Authentication |
| `POST` | `/api/auth/forgot-password` | None |  | Authentication |
| `POST` | `/api/auth/login` | None |  | Authentication |
| `POST` | `/api/auth/logout` | JWT |  | Authentication |
| `POST` | `/api/auth/logout-all` | JWT |  | Authentication |
| `GET` | `/api/auth/me` | JWT |  | Authentication |
| `POST` | `/api/auth/refresh` | None |  | Authentication |
| `POST` | `/api/auth/register` | None |  | Authentication |
| `POST` | `/api/auth/resend-verification` | None |  | Authentication |
| `POST` | `/api/auth/reset-password` | None |  | Authentication |
| `GET` | `/api/auth/sessions` | JWT |  | Authentication |
| `DELETE` | `/api/auth/sessions` | JWT |  | Authentication |
| `DELETE` | `/api/auth/sessions/{session_id}` | JWT |  | Authentication |
| `GET` | `/api/auth/verify-email` | None |  | Authentication |
| `GET` | `/api/backtesting/list` | JWT |  | Backtesting |
| `POST` | `/api/backtesting/multi-symbol` | JWT | Run multi-symbol backtest | Backtesting |
| `GET` | `/api/backtesting/multi-symbol/latest` | JWT | Latest multi-symbol backtest report | Backtesting |
| `GET` | `/api/backtesting/reconciled/investigation` | JWT | Reconciled backtest root cause investigation results | Backtesting |
| `POST` | `/api/backtesting/reconciled/investigation/refresh` | JWT | Re-run reconciled backtest root cause investigation | Backtesting |
| `GET` | `/api/backtesting/replay/regimes` | None | List available stress regimes | Backtesting |
| `POST` | `/api/backtesting/replay/run` | JWT | Run tick-level backtest via Dukascopy replay | Backtesting |
| `POST` | `/api/backtesting/replay/stress` | JWT | Regime-shift stress test across historical regimes | Backtesting |
| `GET` | `/api/backtesting/results` | JWT |  | Backtesting |
| `GET` | `/api/backtesting/results/{run_id}` | JWT |  | Backtesting |
| `POST` | `/api/backtesting/run` | JWT |  | Backtesting |
| `GET` | `/api/backtesting/shared/{slug}` | None |  | Advanced Trading (public) |
| `GET` | `/api/backtesting/strategies` | JWT |  | Backtesting |
| `GET` | `/api/backtesting/walk-forward` | JWT | List all walk-forward results | Backtesting |
| `GET` | `/api/backtesting/walk-forward/latest` | JWT |  | Backtesting |
| `POST` | `/api/backtesting/walk-forward/run` | JWT |  | Backtesting |
| `GET` | `/api/backtesting/walk-forward/{run_id}` | JWT |  | Backtesting |
| `GET` | `/api/backtesting/{run_id}/monte-carlo` | JWT |  | Advanced Trading |
| `POST` | `/api/backtesting/{run_id}/monte-carlo` | JWT |  | Advanced Trading |
| `GET` | `/api/backtesting/{run_id}/report.pdf` | JWT | Download backtest report as PDF | Backtesting |
| `POST` | `/api/backtesting/{run_id}/share` | JWT |  | Advanced Trading |
| `POST` | `/api/billing/affiliate/generate-link` | JWT |  | Billing |
| `POST` | `/api/billing/auth/activate-free-tier` | JWT |  | Billing |
| `GET` | `/api/billing/balance` | JWT |  | Billing |
| `POST` | `/api/billing/crypto/order` | JWT | Create a crypto payment order | Billing |
| `GET` | `/api/billing/crypto/order/{order_id}` | JWT | Get crypto order status | Billing |
| `POST` | `/api/billing/crypto/order/{order_id}/cancel` | JWT | Cancel a pending crypto order | Billing |
| `GET` | `/api/billing/crypto/rates` | JWT | Live crypto exchange rates for checkout | Billing |
| `GET` | `/api/billing/elite/account-manager` | JWT | Get dedicated account manager contact (Elite) | Billing |
| `POST` | `/api/billing/elite/custom-dev/request` | JWT | Submit a custom development request (Elite) | Billing |
| `GET` | `/api/billing/elite/custom-dev/requests` | JWT | List custom development requests for the authenticated Elite user | Billing |
| `POST` | `/api/billing/elite/support/ticket` | JWT | Submit a dedicated support ticket (Elite) | Billing |
| `GET` | `/api/billing/elite/support/tickets` | JWT | List support tickets for the authenticated Elite user | Billing |
| `GET` | `/api/billing/elite/support/tickets/{ticket_id}/timeline` | JWT | Event timeline for a specific Elite support ticket | Billing |
| `GET` | `/api/billing/invoices` | JWT | List invoices | Billing |
| `GET` | `/api/billing/invoices/{invoice_id}` | JWT | Get invoice detail | Billing |
| `GET` | `/api/billing/payment-methods` | JWT |  | Billing |
| `POST` | `/api/billing/payment-methods` | JWT |  | Billing |
| `DELETE` | `/api/billing/payment-methods/{payment_method_id}` | JWT |  | Billing |
| `POST` | `/api/billing/payment-methods/{payment_method_id}/default` | JWT | Set default payment method | Billing |
| `POST` | `/api/billing/payments/flutterwave/init` | JWT |  | Billing |
| `GET` | `/api/billing/payments/flutterwave/status` | None |  | Billing |
| `POST` | `/api/billing/payments/flutterwave/verify` | JWT |  | Billing |
| `GET` | `/api/billing/plans` | None | List available subscription plans | Billing |
| `GET` | `/api/billing/stripe/config` | None |  | Billing |
| `POST` | `/api/billing/stripe/payment-intent` | JWT |  | Billing |
| `GET` | `/api/billing/subscription` | JWT |  | Billing |
| `POST` | `/api/billing/subscription/cancel` | JWT | Cancel active subscription | Billing |
| `POST` | `/api/billing/subscription/change` | JWT | Change subscription plan | Billing |
| `POST` | `/api/billing/subscription/resume` | JWT | Resume cancelled subscription | Billing |
| `GET` | `/api/billing/transactions` | JWT |  | Billing |
| `POST` | `/api/billing/webhook/stripe` | None |  | Billing |
| `POST` | `/api/brain/analyze` | JWT | Run AI analysis on a symbol/timeframe | AI Brain |
| `POST` | `/api/brain/chat` | JWT |  | AI Brain |
| `POST` | `/api/brain/complete` | JWT | Raw LLM completion | AI Brain |
| `POST` | `/api/brain/deploy-strategy` | JWT |  | AI Brain |
| `POST` | `/api/brain/embed` | JWT | Generate text embeddings | AI Brain |
| `POST` | `/api/brain/generate-strategy` | JWT |  | AI Brain |
| `GET` | `/api/brain/health` | JWT | LLM backend health probe | AI Brain |
| `GET` | `/api/brain/insights` | JWT | AI-generated trading insights | AI Brain |
| `GET` | `/api/brain/market-analysis` | JWT | Current market analysis for XAU/USD | AI Brain |
| `GET` | `/api/brain/status` | JWT | AI Brain system status | AI Brain |
| `GET` | `/api/brain/strategies` | JWT | List AI-generated strategies | AI Brain |
| `GET` | `/api/brain/strategies/{strategy_id}` | JWT | Get a specific AI strategy | AI Brain |
| `DELETE` | `/api/brain/strategies/{strategy_id}` | JWT | Delete an AI strategy | AI Brain |
| `POST` | `/api/brain/strategies/{strategy_id}/activate` | JWT | Activate a strategy for paper trading | AI Brain |
| `POST` | `/api/brain/strategies/{strategy_id}/backtest` | JWT | Re-run backtest on a strategy | AI Brain |
| `POST` | `/api/brain/strategies/{strategy_id}/deactivate` | JWT | Deactivate a strategy | AI Brain |
| `GET` | `/api/broker/paper-clock` | JWT | OANDA paper trading clock — elapsed/remaining days and account status | Broker |
| `POST` | `/api/broker/stamp-oanda` | JWT | Stamp real OANDA account_id into the paper trading clock (admin) | Broker |
| `GET` | `/api/broker/status` | JWT | Current broker connection status, balance, and data feed | Broker |
| `POST` | `/api/broker/test-connection` | JWT |  | Broker |
| `GET` | `/api/calendar/auto-pause` | JWT |  | Economic Calendar |
| `POST` | `/api/calendar/auto-pause` | JWT |  | Economic Calendar |
| `GET` | `/api/calendar/fomc` | JWT |  | Economic Calendar |
| `GET` | `/api/calendar/fomc/regime` | JWT |  | Economic Calendar |
| `POST` | `/api/calendar/fomc/regime` | JWT |  | Economic Calendar |
| `DELETE` | `/api/calendar/fomc/regime` | JWT |  | Economic Calendar |
| `GET` | `/api/calendar/high-impact` | JWT |  | Economic Calendar |
| `GET` | `/api/calendar/today` | JWT |  | Economic Calendar |
| `GET` | `/api/calendar/upcoming` | JWT |  | Economic Calendar |
| `GET` | `/api/chaos/mutation/results` | JWT |  | Chaos & Mutation Testing |
| `POST` | `/api/chaos/mutation/run` | JWT |  | Chaos & Mutation Testing |
| `GET` | `/api/chaos/results` | JWT |  | Chaos & Mutation Testing |
| `POST` | `/api/chaos/run` | JWT |  | Chaos & Mutation Testing |
| `POST` | `/api/chaos/scenario/{scenario_name}` | JWT |  | Chaos & Mutation Testing |
| `GET` | `/api/chaos/status` | JWT |  | Chaos & Mutation Testing |
| `POST` | `/api/chat` | JWT | Send a message to the AI assistant | AI Chat |
| `GET` | `/api/chat/dm/{target_user_id}` | JWT |  | Community Chat |
| `POST` | `/api/chat/dm/{target_user_id}` | JWT |  | Community Chat |
| `DELETE` | `/api/chat/history` | JWT | Clear conversation history for a session | AI Chat |
| `GET` | `/api/chat/online` | JWT |  | Community Chat |
| `GET` | `/api/chat/rooms` | JWT |  | Community Chat |
| `POST` | `/api/chat/rooms` | JWT |  | Community Chat |
| `GET` | `/api/chat/rooms/{room_id}` | JWT |  | Community Chat |
| `GET` | `/api/chat/rooms/{room_id}/messages` | JWT |  | Community Chat |
| `POST` | `/api/chat/rooms/{room_id}/messages` | JWT |  | Community Chat |
| `DELETE` | `/api/chat/rooms/{room_id}/messages/{msg_id}` | JWT |  | Community Chat |
| `POST` | `/api/chat/rooms/{room_id}/messages/{msg_id}/reactions` | JWT |  | Community Chat |
| `DELETE` | `/api/chat/rooms/{room_id}/messages/{msg_id}/reactions/{emoji}` | JWT |  | Community Chat |
| `POST` | `/api/chat/rooms/{room_id}/read` | JWT |  | Community Chat |
| `GET` | `/api/chat/status` | JWT | AI chat readiness check | AI Chat |
| `GET` | `/api/control-plane/audit` | JWT |  | Control Plane |
| `GET` | `/api/control-plane/configuration` | JWT |  | Control Plane |
| `POST` | `/api/control-plane/configuration/apply` | JWT |  | Control Plane |
| `GET` | `/api/control-plane/readiness` | JWT |  | Control Plane |
| `POST` | `/api/control-plane/readiness/reprobe` | JWT |  | Control Plane |
| `POST` | `/api/control-plane/sandbox/test` | JWT |  | Control Plane |
| `POST` | `/api/control-plane/startup/restart` | JWT |  | Control Plane |
| `GET` | `/api/control-plane/versions` | JWT |  | Control Plane |
| `GET` | `/api/control-plane/{domain}` | JWT |  | Control Plane |
| `POST` | `/api/control-plane/{domain}/health` | JWT |  | Control Plane |
| `POST` | `/api/copy-trading/copies/{copy_id}/pause` | JWT |  | Copy Trading |
| `GET` | `/api/copy-trading/copies/{copy_id}/performance` | JWT |  | Copy Trading |
| `POST` | `/api/copy-trading/copies/{copy_id}/resume` | JWT |  | Copy Trading |
| `PATCH` | `/api/copy-trading/copies/{copy_id}/risk` | JWT |  | Copy Trading |
| `POST` | `/api/copy-trading/copies/{copy_id}/stop` | JWT |  | Copy Trading |
| `GET` | `/api/copy-trading/masters` | None |  | Copy Trading |
| `GET` | `/api/copy-trading/my-copies` | JWT |  | Copy Trading |
| `GET` | `/api/copy/active` | JWT | List active copy relationships | Copy Trading, Copy Trading |
| `GET` | `/api/copy/history` | JWT | Copy trading history | Copy Trading, Copy Trading |
| `POST` | `/api/copy/{trader_id}` | JWT | Subscribe to copy a trader's signals | Social Feed |
| `DELETE` | `/api/copy/{trader_id}` | JWT | Stop copying a trader | Copy Trading, Copy Trading |
| `PATCH` | `/api/copy/{trader_id}/allocation` | JWT | Update copy allocation | Copy Trading, Copy Trading |
| `GET` | `/api/copy/{trader_id}/performance` | JWT | Copy trader performance | Copy Trading, Copy Trading |
| `GET` | `/api/custom-indicators` | JWT | List user's custom indicators | Custom Indicators |
| `POST` | `/api/custom-indicators` | JWT | Create a custom indicator | Custom Indicators |
| `GET` | `/api/custom-indicators/builtin` | None | List all built-in indicators | Custom Indicators |
| `POST` | `/api/custom-indicators/calculate` | JWT | Calculate a built-in indicator on provided data | Custom Indicators |
| `POST` | `/api/custom-indicators/preview` | JWT | Preview a custom indicator formula | Custom Indicators |
| `GET` | `/api/custom-indicators/{indicator_id}` | JWT | Get a specific custom indicator | Custom Indicators |
| `PUT` | `/api/custom-indicators/{indicator_id}` | JWT | Replace a custom indicator (full update) | Custom Indicators |
| `PATCH` | `/api/custom-indicators/{indicator_id}` | JWT | Update a custom indicator | Custom Indicators |
| `DELETE` | `/api/custom-indicators/{indicator_id}` | JWT | Delete a custom indicator | Custom Indicators |
| `POST` | `/api/custom-indicators/{indicator_id}/apply` | JWT | Apply indicator to a symbol/timeframe | Custom Indicators |
| `POST` | `/api/custom-indicators/{indicator_id}/deploy` | JWT | Deploy a custom indicator to the live chart engine | Custom Indicators |
| `POST` | `/api/custom-indicators/{indicator_id}/test` | JWT | Test a custom indicator against live/recent data | Custom Indicators |
| `GET` | `/api/dashboard/{symbol}/bias` | None |  | Order Flow Dashboard |
| `GET` | `/api/dashboard/{symbol}/complete` | None |  | Order Flow Dashboard |
| `GET` | `/api/dashboard/{symbol}/levels` | None |  | Order Flow Dashboard |
| `GET` | `/api/data-layer/feeds` | JWT |  | Data Layer |
| `GET` | `/api/data-layer/health` | JWT |  | Data Layer |
| `GET` | `/api/data-layer/lineage` | JWT |  | Data Layer |
| `GET` | `/api/data-layer/macro` | JWT |  | Data Layer |
| `GET` | `/api/data-layer/microstructure` | JWT |  | Data Layer |
| `GET` | `/api/data-layer/ml-features` | JWT |  | Data Layer |
| `GET` | `/api/data-layer/quality` | JWT |  | Data Layer |
| `GET` | `/api/data-layer/sentiment` | JWT |  | Data Layer |
| `GET` | `/api/data-layer/tick` | JWT |  | Data Layer |
| `GET` | `/api/dom/` | None |  | Depth of Market |
| `GET` | `/api/dom/stats` | None |  | Depth of Market |
| `GET` | `/api/dom/{symbol}` | None |  | Depth of Market |
| `GET` | `/api/dom/{symbol}/analysis` | None |  | Depth of Market |
| `GET` | `/api/dom/{symbol}/history` | None |  | Depth of Market |
| `GET` | `/api/dom/{symbol}/imbalance` | None |  | Depth of Market |
| `GET` | `/api/dom/{symbol}/visualization` | None |  | Depth of Market |
| `GET` | `/api/explain/latest` | JWT | Explain the latest signal | Explainability |
| `GET` | `/api/explain/signal/{signal_id}` | JWT | Explain a specific signal | Explainability |
| `GET` | `/api/explain/{signal_id}` | JWT | Explain a signal by ID or symbol (short-form alias) | Explainability |
| `POST` | `/api/explain/{signal_id}` | JWT | Explain a signal by ID or symbol (POST alias) | Explainability |
| `POST` | `/api/explainability/counterfactual` | JWT |  | Explainability |
| `POST` | `/api/explainability/explain` | JWT |  | Explainability |
| `GET` | `/api/explainability/explanation/{explanation_id}/chart` | JWT |  | Explainability |
| `GET` | `/api/explainability/history` | JWT |  | Explainability |
| `GET` | `/api/explainability/model/{model_name}/performance` | JWT |  | Explainability |
| `GET` | `/api/feed` | None |  | Social Feed |
| `POST` | `/api/feed/opt-in` | JWT |  | Social Feed |
| `POST` | `/api/feed/opt-out` | JWT |  | Social Feed |
| `GET` | `/api/feed/status` | JWT |  | Social Feed |
| `GET` | `/api/feed/status/me` | JWT |  | Social Feed |
| `POST` | `/api/feed/{signal_id}/comment` | JWT |  | Social Feed |
| `GET` | `/api/feed/{signal_id}/comments` | None |  | Social Feed |
| `POST` | `/api/feed/{signal_id}/react` | JWT |  | Social Feed |
| `GET` | `/api/health/components` | None | Full structured component health report | Observability |
| `GET` | `/api/health/deep` | None | Deep health check — real I/O probes against every dependency | Observability |
| `GET` | `/api/health/live` | None | Liveness probe — always 200 if process is alive | Observability |
| `GET` | `/api/health/metrics` | None | Prometheus-compatible text/plain metrics snapshot | Observability |
| `GET` | `/api/health/ready` | None | Readiness probe — 503 when any critical component is down | Observability |
| `GET` | `/api/health/startup` | None | Startup probe — 503 until application fully initialised | Observability |
| `GET` | `/api/indicators` | JWT |  | Advanced Trading |
| `POST` | `/api/indicators` | JWT |  | Advanced Trading |
| `POST` | `/api/indicators/preview` | JWT |  | Advanced Trading |
| `PATCH` | `/api/indicators/{ind_id}` | JWT |  | Advanced Trading |
| `DELETE` | `/api/indicators/{ind_id}` | JWT |  | Advanced Trading |
| `POST` | `/api/indicators/{ind_id}/apply` | JWT |  | Advanced Trading |
| `GET` | `/api/journal` | JWT | List journal entries (root alias) | Trade Journal |
| `GET` | `/api/journal/emotion-stats` | JWT | Emotion breakdown across journal entries | Trade Journal |
| `GET` | `/api/journal/export` | JWT | Export journal entries as CSV or JSON | Trade Journal |
| `GET` | `/api/journal/mistakes` | JWT |  | Trade Journal |
| `GET` | `/api/journal/stats` | JWT |  | Trade Journal |
| `GET` | `/api/journal/tags` | JWT | List all tags used across journal entries | Trade Journal |
| `GET` | `/api/journal/trades` | JWT |  | Trade Journal |
| `POST` | `/api/journal/trades` | JWT |  | Trade Journal |
| `GET` | `/api/journal/trades/{trade_id}` | JWT |  | Trade Journal |
| `PATCH` | `/api/journal/trades/{trade_id}` | JWT |  | Trade Journal |
| `POST` | `/api/journal/trades/{trade_id}/screenshot` | JWT | Attach a screenshot to a journal entry | Trade Journal |
| `GET` | `/api/journal/weekly-report` | JWT | Weekly performance summary from journal | Trade Journal |
| `GET` | `/api/kyc/documents` | JWT | List KYC documents (alias) | KYC |
| `POST` | `/api/kyc/documents` | JWT | Upload KYC document | KYC |
| `GET` | `/api/kyc/status` | JWT | KYC status (alias) | KYC |
| `POST` | `/api/kyc/submit` | JWT | Submit KYC application (alias) | KYC |
| `POST` | `/api/kyc/upload` | JWT | Upload KYC document (alias for /documents) | KYC |
| `GET` | `/api/leaderboard` | None | Trader performance leaderboard | Social Feed |
| `GET` | `/api/leaderboard/{trader_id}` | None | Trader leaderboard profile | Social Feed |
| `GET` | `/api/leaderboard/{trader_id}/stats` | None | Trader leaderboard stats | Social Feed |
| `GET` | `/api/macro/features` | JWT | Macro features for ML inference | Macro Data |
| `GET` | `/api/macro/refresh` | JWT | Force-refresh macro data from FRED and update MacroStore | Macro Data |
| `GET` | `/api/macro/snapshot` | None | Current macro snapshot for gold | Macro Data |
| `GET` | `/api/macro/store` | JWT | MacroStore snapshot — all loaded series with latest values | Macro Data |
| `POST` | `/api/macro/store/update` | JWT | Upsert a macro observation into MacroStore | Macro Data |
| `GET` | `/api/macro/wgc` | None | WGC gold demand snapshot — latest values from MacroStore | Macro Data |
| `GET` | `/api/macro/wgc/health` | None | WGC feed health — cache status and loaded series | Macro Data |
| `POST` | `/api/macro/wgc/refresh` | JWT | Force-refresh WGC gold demand data and inject into MacroStore | Macro Data |
| `GET` | `/api/ml/ab-tests` | JWT | List all active A/B tests | ML Models, ML Models |
| `POST` | `/api/ml/ab-tests` | JWT | Create a new A/B test | ML Models, ML Models |
| `DELETE` | `/api/ml/ab-tests/{test_id}` | JWT | Stop an A/B test | ML Models, ML Models |
| `POST` | `/api/ml/ab-tests/{test_id}/result` | JWT | Record a prediction result for an A/B test | ML Models, ML Models |
| `GET` | `/api/ml/accuracy` | JWT |  | ML Models |
| `GET` | `/api/ml/anomaly/config` | JWT | Anomaly detector configuration | Anomaly Detection |
| `POST` | `/api/ml/anomaly/fit` | JWT | Fit anomaly detector on historical OHLCV data | Anomaly Detection |
| `POST` | `/api/ml/anomaly/flag` | JWT | Return indices of anomalous bars | Anomaly Detection |
| `GET` | `/api/ml/anomaly/report/{symbol}` | JWT | Top-N most anomalous bars for a symbol | Anomaly Detection |
| `DELETE` | `/api/ml/anomaly/reset` | JWT | Reset the live anomaly store (admin) | Anomaly Detection |
| `POST` | `/api/ml/anomaly/retrain` | JWT | Background refit on latest market data (admin) | Anomaly Detection |
| `POST` | `/api/ml/anomaly/score` | JWT | Score recent OHLCV bars for anomalies | Anomaly Detection |
| `GET` | `/api/ml/anomaly/status` | JWT | Live anomaly detector status | Anomaly Detection |
| `GET` | `/api/ml/drift-report` | JWT | Real-time feature drift report (PSI + KS-test) | ML Models, ML Models |
| `GET` | `/api/ml/drift/status` | JWT | Live feature drift status | ML Models, ML Models |
| `GET` | `/api/ml/engine-health` | JWT | InferenceEngine detailed health (admin) | ML Models |
| `GET` | `/api/ml/explain/{model_name}` | JWT | SHAP feature importance for a deployed model | ML Models, ML Models |
| `GET` | `/api/ml/feature-importance/{model_name}` | JWT | Built-in feature importances for a deployed model (fast) | ML Models, ML Models |
| `GET` | `/api/ml/features` | JWT | Feature importances for the active XGBoost model | ML Models |
| `GET` | `/api/ml/health` | JWT | ML model health check | ML Models |
| `GET` | `/api/ml/model-card` | JWT | Formal Model Card — metadata, performance, drift status, limitations | ML Models |
| `GET` | `/api/ml/model-drift` | JWT | KS-test model-output drift across all production models | ML Models, ML Models |
| `GET` | `/api/ml/models` | JWT |  | ML Models |
| `POST` | `/api/ml/predict/{symbol}` | JWT |  | ML Models |
| `POST` | `/api/ml/retrain` | JWT | Trigger background model retraining (admin only) | ML Models |
| `GET` | `/api/ml/rl/status` | JWT |  | ML Models, ML Models |
| `POST` | `/api/ml/rl/train` | JWT |  | ML Models, ML Models |
| `POST` | `/api/ml/rl/walk-forward` | JWT |  | ML Models, ML Models |
| `GET` | `/api/ml/sharpe-circuit-breaker/status` | JWT | Sharpe circuit breaker state for all tracked model versions | ML Models, ML Models |
| `GET` | `/api/ml/signal-filter/stats` | JWT | Signal filter EV statistics — rolling win rate, avg win/loss, EV gate status | ML Models |
| `GET` | `/api/ml/training-jobs` | JWT | List all training jobs (active + recent) | ML Models, ML Models |
| `POST` | `/api/ml/training-jobs` | JWT | Start a model training job | ML Models, ML Models |
| `DELETE` | `/api/ml/training-jobs/{job_id}` | JWT | Cancel a running training job | ML Models, ML Models |
| `GET` | `/api/mlops/drift` | JWT |  | MLOps |
| `GET` | `/api/mlops/health` | JWT |  | MLOps |
| `GET` | `/api/mlops/models/{version_id}/metrics` | JWT |  | MLOps |
| `POST` | `/api/mlops/promote/{version_id}` | JWT |  | MLOps |
| `POST` | `/api/mlops/retrain` | JWT |  | MLOps |
| `GET` | `/api/mlops/retrain/history` | JWT |  | MLOps |
| `GET` | `/api/mlops/shadow` | JWT |  | MLOps |
| `GET` | `/api/mobile/config` | JWT | Mobile app configuration | Mobile |
| `GET` | `/api/mobile/notification-prefs` | JWT | Get notification preferences | Mobile |
| `PATCH` | `/api/mobile/notification-prefs` | JWT | Update notification preferences | Mobile |
| `GET` | `/api/mobile/push-status` | JWT |  | Mobile |
| `POST` | `/api/mobile/push-token` | JWT | Register Expo push token (React Native) | Mobile |
| `POST` | `/api/mobile/register-push` | JWT |  | Mobile |
| `DELETE` | `/api/mobile/register-push` | JWT |  | Mobile |
| `GET` | `/api/mobile/sessions` | JWT | Active mobile sessions | Mobile |
| `DELETE` | `/api/mobile/sessions/{session_id}` | JWT | Revoke a mobile session | Mobile |
| `POST` | `/api/mobile/test-push` | JWT |  | Mobile |
| `POST` | `/api/monetization/activate-code` | JWT |  | Monetization |
| `GET` | `/api/monetization/affiliate/leaderboard` | JWT |  | Monetization |
| `POST` | `/api/monetization/affiliate/referral` | JWT |  | Monetization |
| `POST` | `/api/monetization/affiliate/signup` | JWT |  | Monetization |
| `GET` | `/api/monetization/affiliate/{affiliate_id}/commissions` | JWT |  | Monetization |
| `PATCH` | `/api/monetization/affiliate/{affiliate_id}/payment-method` | JWT |  | Monetization |
| `GET` | `/api/monetization/affiliate/{affiliate_id}/referrals` | JWT |  | Monetization |
| `POST` | `/api/monetization/affiliate/{affiliate_id}/withdraw` | JWT |  | Monetization |
| `GET` | `/api/monetization/affiliate/{user_id}` | JWT |  | Monetization |
| `GET` | `/api/monetization/analytics/dashboard` | JWT |  | Monetization |
| `GET` | `/api/monetization/analytics/growth` | JWT |  | Monetization |
| `GET` | `/api/monetization/analytics/report` | JWT |  | Monetization |
| `GET` | `/api/monetization/analytics/revenue` | JWT |  | Monetization |
| `GET` | `/api/monetization/enterprise/stats` | JWT |  | Monetization |
| `POST` | `/api/monetization/license/validate` | JWT |  | Monetization |
| `POST` | `/api/monetization/marketplace/creators/stripe-account` | JWT |  | Monetization |
| `GET` | `/api/monetization/marketplace/creators/{creator_id}/balance` | JWT |  | Monetization |
| `GET` | `/api/monetization/marketplace/creators/{creator_id}/payouts` | JWT |  | Monetization |
| `GET` | `/api/monetization/marketplace/creators/{creator_id}/transactions` | JWT |  | Monetization |
| `GET` | `/api/monetization/marketplace/featured` | JWT |  | Monetization |
| `POST` | `/api/monetization/marketplace/list` | JWT |  | Monetization |
| `POST` | `/api/monetization/marketplace/payouts/process` | JWT |  | Monetization |
| `GET` | `/api/monetization/marketplace/platform/revenue` | JWT |  | Monetization |
| `POST` | `/api/monetization/marketplace/purchase` | JWT |  | Monetization |
| `POST` | `/api/monetization/marketplace/review` | JWT |  | Monetization |
| `POST` | `/api/monetization/marketplace/sales` | JWT |  | Monetization |
| `GET` | `/api/monetization/marketplace/stats` | JWT |  | Monetization |
| `GET` | `/api/monetization/marketplace/strategies` | JWT |  | Monetization |
| `GET` | `/api/monetization/marketplace/strategies/{strategy_id}` | JWT |  | Monetization |
| `GET` | `/api/monetization/marketplace/strategies/{strategy_id}/reviews` | JWT |  | Monetization |
| `POST` | `/api/monetization/marketplace/strategies/{strategy_id}/reviews` | JWT |  | Monetization |
| `GET` | `/api/monetization/marketplace/submissions/creator/{creator_id}` | JWT |  | Monetization |
| `GET` | `/api/monetization/marketplace/submissions/pending` | JWT |  | Monetization |
| `GET` | `/api/monetization/marketplace/submissions/{submission_id}` | JWT |  | Monetization |
| `POST` | `/api/monetization/marketplace/submissions/{submission_id}/approve` | JWT |  | Monetization |
| `POST` | `/api/monetization/marketplace/submissions/{submission_id}/reject` | JWT |  | Monetization |
| `POST` | `/api/monetization/marketplace/submit` | JWT |  | Monetization |
| `GET` | `/api/monetization/marketplace/subscriptions` | JWT | User's marketplace subscriptions | Monetization |
| `DELETE` | `/api/monetization/marketplace/subscriptions/{strategy_id}` | JWT | Cancel a marketplace strategy subscription | Monetization |
| `POST` | `/api/monetization/partner/signup` | JWT |  | Monetization |
| `GET` | `/api/monetization/partner/{partner_id}` | JWT |  | Monetization |
| `GET` | `/api/monetization/pricing` | JWT |  | Monetization |
| `GET` | `/api/monetization/pricing/{tier}` | JWT |  | Monetization |
| `POST` | `/api/monetization/subscribe` | JWT |  | Monetization |
| `POST` | `/api/monetization/subscription/{subscription_id}/cancel` | JWT |  | Monetization |
| `GET` | `/api/monetization/subscription/{user_id}` | JWT |  | Monetization |
| `GET` | `/api/monetization/subscription/{user_id}/limits` | JWT |  | Monetization |
| `GET` | `/api/monetization/validate-code/{code}` | JWT |  | Monetization |
| `POST` | `/api/monetization/webhook/stripe` | None |  | Monetization |
| `POST` | `/api/monetization/white-label/create` | JWT |  | Monetization |
| `GET` | `/api/news/calendar` | None |  | News Feed |
| `GET` | `/api/news/economic/upcoming` | None |  | News & Geopolitical Intelligence |
| `GET` | `/api/news/feed` | None |  | News Feed |
| `GET` | `/api/news/geopolitical/assessment` | None |  | News & Geopolitical Intelligence |
| `GET` | `/api/news/geopolitical/events` | None |  | News & Geopolitical Intelligence |
| `GET` | `/api/news/geopolitical/signal` | None |  | News & Geopolitical Intelligence |
| `GET` | `/api/news/geopolitical/world-monitor` | None |  | News & Geopolitical Intelligence |
| `GET` | `/api/news/latest` | None |  | News & Geopolitical Intelligence |
| `GET` | `/api/news/nuclear-score` | None |  | News Feed |
| `GET` | `/api/news/sentiment` | None |  | News & Geopolitical Intelligence |
| `GET` | `/api/news/sentiment/{symbol}` | None |  | News & Geopolitical Intelligence |
| `GET` | `/api/nocode/blocks` | JWT |  | No-Code Builder |
| `POST` | `/api/nocode/deploy` | JWT |  | No-Code Builder, No-Code Builder |
| `GET` | `/api/nocode/indicators` | JWT |  | No-Code Builder |
| `GET` | `/api/nocode/node-types` | JWT |  | No-Code Builder, No-Code Builder |
| `GET` | `/api/nocode/strategies` | JWT |  | No-Code Builder |
| `POST` | `/api/nocode/strategies` | JWT |  | No-Code Builder |
| `POST` | `/api/nocode/strategies/from-template/{template_id}` | JWT |  | No-Code Builder |
| `POST` | `/api/nocode/strategies/parse` | JWT |  | No-Code Builder |
| `GET` | `/api/nocode/strategies/{strategy_id}` | JWT |  | No-Code Builder |
| `PATCH` | `/api/nocode/strategies/{strategy_id}` | JWT |  | No-Code Builder |
| `DELETE` | `/api/nocode/strategies/{strategy_id}` | JWT |  | No-Code Builder |
| `POST` | `/api/nocode/strategies/{strategy_id}/backtest` | JWT |  | No-Code Builder |
| `POST` | `/api/nocode/strategies/{strategy_id}/compile` | JWT |  | No-Code Builder |
| `GET` | `/api/nocode/strategies/{strategy_id}/export` | JWT |  | No-Code Builder |
| `GET` | `/api/nocode/templates` | JWT |  | No-Code Builder |
| `POST` | `/api/nocode/validate` | JWT |  | No-Code Builder, No-Code Builder |
| `GET` | `/api/notifications` | JWT |  | Notifications, Notifications |
| `GET` | `/api/notifications/` | JWT |  | Notifications, Notifications |
| `POST` | `/api/notifications/mark-all-read` | JWT |  | Notifications, Notifications |
| `GET` | `/api/notifications/preferences` | JWT |  | Notifications, Notifications |
| `PATCH` | `/api/notifications/preferences` | JWT |  | Notifications, Notifications |
| `POST` | `/api/notifications/subscribe` | JWT |  | Notifications, Notifications |
| `POST` | `/api/notifications/test` | JWT | Send a test notification | Settings |
| `GET` | `/api/notifications/unread-count` | JWT |  | Notifications, Notifications |
| `DELETE` | `/api/notifications/{notif_id}` | JWT |  | Notifications, Notifications |
| `PATCH` | `/api/notifications/{notif_id}/read` | JWT |  | Notifications, Notifications |
| `POST` | `/api/nuclear-strategy/agent/start` | JWT | Start the nuclear strategy agent |  |
| `POST` | `/api/nuclear-strategy/agent/stop` | JWT | Stop the nuclear strategy agent |  |
| `GET` | `/api/nuclear-strategy/analyze` | JWT | Run full nuclear strategy pipeline |  |
| `POST` | `/api/nuclear-strategy/analyze/force` | JWT | Force a fresh pipeline run |  |
| `GET` | `/api/nuclear-strategy/backtest` | JWT | Latest shadow backtest result |  |
| `GET` | `/api/nuclear-strategy/cone` | JWT | Latest ITOS cone (merged multi-TF) |  |
| `GET` | `/api/nuclear-strategy/features` | JWT | Latest multi-timeframe features |  |
| `GET` | `/api/nuclear-strategy/history` | JWT | Approved signal history |  |
| `DELETE` | `/api/nuclear-strategy/history` | JWT | Clear approved signal history |  |
| `GET` | `/api/nuclear-strategy/regime` | JWT | Current regime + transition history |  |
| `GET` | `/api/nuclear-strategy/signal` | JWT | Latest NuclearSignal |  |
| `GET` | `/api/nuclear-strategy/status` | JWT | Nuclear strategy agent status |  |
| `GET` | `/api/nuclear-strategy/stream/status` | JWT | Redis stream reader status |  |
| `POST` | `/api/nuclear/event` | JWT | Inject a news event for immediate nuclear scoring |  |
| `POST` | `/api/nuclear/hedge/activate` | JWT | Activate hedge mode on a symbol |  |
| `POST` | `/api/nuclear/hedge/deactivate` | JWT | Deactivate hedge mode and close all hedge positions |  |
| `GET` | `/api/nuclear/history` | JWT | Last N nuclear supervisor events |  |
| `POST` | `/api/nuclear/kill_switch/activate` | JWT | Manually activate the kill switch |  |
| `POST` | `/api/nuclear/kill_switch/deactivate` | JWT | Deactivate the kill switch |  |
| `POST` | `/api/nuclear/resume` | JWT | Manually resume trading after nuclear halt |  |
| `POST` | `/api/nuclear/set_risk` | JWT | Override the global max-risk fraction |  |
| `GET` | `/api/nuclear/snapshot` | None | Real-time NuclearChartState snapshot (HTTP polling fallback) |  |
| `GET` | `/api/nuclear/status` | JWT | Nuclear supervisor + risk orchestrator status |  |
| `GET` | `/api/observability/alerts` | JWT |  | Observability |
| `GET` | `/api/observability/latency-histogram` | JWT |  | Observability |
| `GET` | `/api/observability/metrics` | JWT |  | Observability |
| `GET` | `/api/observability/services` | JWT |  | Observability |
| `GET` | `/api/observability/traces` | JWT |  | Observability |
| `GET` | `/api/online-learner/diagnostics` | JWT | Deep diagnostics for both online learner layers | Online Learner |
| `POST` | `/api/online-learner/partial-fit` | JWT | Trigger incremental SGD update for a symbol | Online Learner |
| `POST` | `/api/online-learner/reset` | JWT | Reset the Phase-3 OnlineLearnerStore for a symbol | Online Learner |
| `GET` | `/api/online-learner/status` | JWT | Online learner status for all registered symbols | Online Learner |
| `GET` | `/api/orderflow/stats` | None |  | Order Flow |
| `GET` | `/api/orderflow/{symbol}/analysis` | None |  | Order Flow |
| `GET` | `/api/orderflow/{symbol}/delta` | None |  | Order Flow |
| `GET` | `/api/orderflow/{symbol}/footprint` | None |  | Order Flow |
| `GET` | `/api/orderflow/{symbol}/levels` | None |  | Order Flow |
| `GET` | `/api/orderflow/{symbol}/profile` | None |  | Order Flow |
| `GET` | `/api/orders/advanced/active` | JWT |  | Advanced Orders |
| `GET` | `/api/orders/advanced/health` | JWT |  | Advanced Orders |
| `POST` | `/api/orders/advanced/oco` | JWT |  | Advanced Orders |
| `POST` | `/api/orders/advanced/stop-limit` | JWT |  | Advanced Orders |
| `POST` | `/api/orders/advanced/trailing-stop` | JWT |  | Advanced Orders |
| `GET` | `/api/orders/advanced/{order_id}` | JWT |  | Advanced Orders |
| `DELETE` | `/api/orders/advanced/{order_id}` | JWT |  | Advanced Orders |
| `POST` | `/api/payments/crypto/address` | JWT |  | Payments |
| `GET` | `/api/payments/crypto/rates` | JWT |  | Payments |
| `GET` | `/api/payments/crypto/status/{payment_id}` | JWT |  | Payments |
| `POST` | `/api/payments/deposit` | JWT | Initiate a fiat deposit | Payments |
| `POST` | `/api/payments/webhook` | None |  | Payments, Payments |
| `POST` | `/api/payments/withdraw` | JWT | Initiate a fiat withdrawal | Payments |
| `GET` | `/api/performance/attribution` | JWT | P&L attribution by factor | Performance |
| `GET` | `/api/performance/equity-curve` | JWT | Equity curve time series | Performance |
| `GET` | `/api/performance/export` | JWT | Export performance data as CSV or JSON | Performance |
| `GET` | `/api/performance/metrics` | JWT | Performance metrics (alias for /summary) | Performance |
| `GET` | `/api/performance/public` | None | Public performance summary | Performance |
| `GET` | `/api/performance/summary` | JWT | Performance summary (alias for /public) | Performance |
| `GET` | `/api/performance/trade-breakdown` | JWT | Trade breakdown by symbol, strategy, session | Performance |
| `POST` | `/api/performance/weekly-report/generate` | JWT | Trigger weekly performance report generation | Performance |
| `GET` | `/api/performance/weekly-report/latest` | JWT | Get the most recent weekly performance report | Performance |
| `GET` | `/api/performance/weekly-report/list` | JWT | List all generated weekly reports | Performance |
| `GET` | `/api/performance/weekly-reports` | JWT | List weekly reports (alias for /weekly-report/list) | Performance |
| `GET` | `/api/pnl/drawdown-curve` | JWT | Drawdown % time series | P&L Dashboard |
| `GET` | `/api/pnl/equity-curve` | JWT | Equity curve time series | P&L Dashboard |
| `GET` | `/api/pnl/export` | JWT | Export P&L data as CSV or JSON | P&L Dashboard |
| `GET` | `/api/pnl/history` | JWT | P&L trade history (closed trades) | P&L Dashboard |
| `GET` | `/api/pnl/open-positions` | JWT | Current open positions with unrealised P&L | P&L Dashboard |
| `GET` | `/api/pnl/summary` | JWT | Live P&L headline stats | P&L Dashboard |
| `GET` | `/api/pnl/trade-log` | JWT | Auditable fill-level trade log | P&L Dashboard |
| `GET` | `/api/portfolio/allocator/correlation` | JWT | Pairwise return correlation matrix for validated pods | Portfolio Allocator |
| `GET` | `/api/portfolio/allocator/pods` | JWT | List all registered strategy pods | Portfolio Allocator |
| `POST` | `/api/portfolio/allocator/pods/register` | JWT | Register a new strategy pod (admin) | Portfolio Allocator |
| `POST` | `/api/portfolio/allocator/pods/return` | JWT | Append a daily return to a strategy pod | Portfolio Allocator |
| `POST` | `/api/portfolio/allocator/pods/update-metrics` | JWT |  | strategy-allocator, strategy-allocator |
| `PUT` | `/api/portfolio/allocator/pods/{name}` | JWT | Update OOS metrics for an existing pod (admin) | Portfolio Allocator |
| `POST` | `/api/portfolio/allocator/recompute` | JWT | Force weight recomputation (admin) | Portfolio Allocator |
| `GET` | `/api/portfolio/allocator/registry` | JWT | Raw edge registry JSON (admin) | Portfolio Allocator |
| `GET` | `/api/portfolio/allocator/status` | JWT | Allocator health and gate configuration | Portfolio Allocator |
| `GET` | `/api/portfolio/allocator/weights` | JWT | Current optimised capital allocation weights | Portfolio Allocator |
| `POST` | `/api/portfolio/factor/attribute` | JWT | Attribute portfolio P&L to systematic factors | Portfolio |
| `GET` | `/api/portfolio/factor/exposures` | JWT | Per-symbol factor beta loadings | Portfolio |
| `GET` | `/api/portfolio/factor/status` | JWT | LiveFactorEngine status | Portfolio |
| `POST` | `/api/portfolio/factor/var` | JWT | Factor-level VaR contributions | Portfolio |
| `GET` | `/api/portfolio/positions` | JWT | Portfolio positions with weights | Portfolio, Portfolio |
| `POST` | `/api/portfolio/rebalancer/rebalance` | JWT | Trigger a portfolio rebalance | Portfolio |
| `POST` | `/api/portfolio/rebalancer/returns` | JWT | Feed a strategy return series into the rebalancer | Portfolio |
| `GET` | `/api/portfolio/rebalancer/status` | JWT | DynamicRebalancer status | Portfolio |
| `GET` | `/api/portfolio/rebalancer/weights` | JWT | Current target weights | Portfolio |
| `GET` | `/api/portfolio/risk/factor-report` | JWT | Combined factor risk report | Portfolio |
| `GET` | `/api/portfolio/summary` | JWT | Portfolio summary | Portfolio, Portfolio |
| `GET` | `/api/portfolio/tick-feed/execution` | JWT | Execution engine tick cache status | Portfolio |
| `GET` | `/api/portfolio/tick-feed/last-tick` | JWT | Latest validated tick | Portfolio |
| `GET` | `/api/portfolio/tick-feed/status` | JWT | TickFeedManager status | Portfolio |
| `GET` | `/api/pricing/compare` | None | Side-by-side feature comparison for two tiers | Pricing |
| `POST` | `/api/pricing/estimate` | None | Estimate monthly cost given usage parameters | Pricing |
| `GET` | `/api/pricing/faq` | None | Pricing FAQ | Pricing |
| `GET` | `/api/pricing/plans` | None | List all subscription plans with full feature matrix | Pricing |
| `GET` | `/api/pricing/upgrade-path` | None | Available upgrade options from current tier | Pricing |
| `GET` | `/api/profiles` | None |  | Profiles |
| `GET` | `/api/profiles/avatar/{name}` | None |  | Profiles |
| `GET` | `/api/profiles/me` | JWT |  | Profiles |
| `PUT` | `/api/profiles/me` | JWT |  | Profiles |
| `POST` | `/api/profiles/me/avatar` | JWT |  | Profiles |
| `GET` | `/api/profiles/{trader_id}` | None |  | Profiles |
| `POST` | `/api/profiles/{trader_id}/follow` | JWT |  | Profiles |
| `DELETE` | `/api/profiles/{trader_id}/follow` | JWT |  | Profiles |
| `GET` | `/api/profiles/{trader_id}/followers` | None |  | Profiles |
| `GET` | `/api/profiles/{trader_id}/following` | None |  | Profiles |
| `GET` | `/api/profiles/{trader_id}/signals` | None |  | Profiles |
| `GET` | `/api/profiles/{trader_id}/stats` | None |  | Profiles |
| `GET` | `/api/profiles/{trader_id}/strategies` | None |  | Profiles |
| `GET` | `/api/public/prices` | None |  | WebSocket Public |
| `GET` | `/api/public/signals` | None |  | WebSocket Public |
| `GET` | `/api/replay/sessions` | JWT |  | Replay |
| `POST` | `/api/replay/sessions` | JWT |  | Replay |
| `GET` | `/api/replay/sessions/{session_id}` | JWT |  | Replay |
| `DELETE` | `/api/replay/sessions/{session_id}` | JWT |  | Replay |
| `POST` | `/api/replay/sessions/{session_id}/orders` | JWT |  | Replay |
| `POST` | `/api/replay/sessions/{session_id}/pause` | JWT |  | Replay |
| `POST` | `/api/replay/sessions/{session_id}/play` | JWT |  | Replay |
| `POST` | `/api/replay/sessions/{session_id}/resume` | JWT |  | Replay |
| `POST` | `/api/replay/sessions/{session_id}/run` | JWT |  | Replay |
| `POST` | `/api/replay/sessions/{session_id}/speed` | JWT |  | Replay |
| `PUT` | `/api/replay/sessions/{session_id}/speed` | JWT |  | Replay |
| `POST` | `/api/replay/sessions/{session_id}/step` | JWT |  | Replay |
| `POST` | `/api/replay/sessions/{session_id}/stop` | JWT |  | Replay |
| `GET` | `/api/replay/sessions/{session_id}/summary` | JWT |  | Replay |
| `GET` | `/api/research/notebooks` | JWT |  | Research |
| `POST` | `/api/research/notebooks` | JWT |  | Research |
| `POST` | `/api/research/notebooks/from-template/{template_id}` | JWT |  | Research |
| `GET` | `/api/research/notebooks/{notebook_id}` | JWT |  | Research |
| `DELETE` | `/api/research/notebooks/{notebook_id}` | JWT |  | Research |
| `POST` | `/api/research/notebooks/{notebook_id}/cells` | JWT |  | Research |
| `POST` | `/api/research/notebooks/{notebook_id}/cells/{cell_id}/execute` | JWT |  | Research |
| `POST` | `/api/research/notebooks/{notebook_id}/execute` | JWT |  | Research |
| `GET` | `/api/research/notebooks/{notebook_id}/export` | JWT |  | Research |
| `POST` | `/api/research/notebooks/{notebook_id}/run` | JWT |  | Research |
| `GET` | `/api/research/templates` | JWT |  | Research |
| `GET` | `/api/risk/calculator/history` | JWT | Saved risk/reward calculations | Risk Calculator |
| `POST` | `/api/risk/calculator/history` | JWT | Save a risk/reward calculation | Risk Calculator |
| `DELETE` | `/api/risk/calculator/history/{calc_id}` | JWT | Delete a saved calculation | Risk Calculator |
| `GET` | `/api/risk/live-price/{symbol}` | JWT | Live mid price for a symbol | Risk Calculator |
| `GET` | `/api/risk/prop-firm-status` | JWT | Prop firm challenge status | Risk / Prop Firm |
| `GET` | `/api/risk/prop-firm/accounts` | JWT | Prop firm accounts | Risk / Prop Firm |
| `GET` | `/api/risk/prop-firm/breach-alerts` | JWT | Prop firm breach alerts | Risk / Prop Firm |
| `POST` | `/api/risk/prop-firm/breach-alerts/{alert_id}/acknowledge` | JWT | Acknowledge a breach alert | Risk / Prop Firm |
| `GET` | `/api/risk/prop-firm/challenges` | JWT | Active prop firm challenges | Risk / Prop Firm |
| `GET` | `/api/risk/prop-firm/daily-stats` | JWT | Daily P&L stats for prop firm | Risk / Prop Firm |
| `GET` | `/api/risk/prop-firm/history` | JWT | Prop firm challenge history | Risk / Prop Firm |
| `POST` | `/api/safe-platform/approvals` | JWT |  | Safe Agent Platform |
| `GET` | `/api/safe-platform/chat/capabilities` | JWT |  | Safe Agent Platform |
| `GET` | `/api/safe-platform/diagnostics/graph` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/diagnostics/run` | JWT |  | Safe Agent Platform |
| `GET` | `/api/safe-platform/integrations` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/integrations/action` | JWT |  | Safe Agent Platform |
| `GET` | `/api/safe-platform/models/health` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/models/route` | JWT |  | Safe Agent Platform |
| `GET` | `/api/safe-platform/models/routes` | JWT |  | Safe Agent Platform |
| `GET` | `/api/safe-platform/overview` | JWT |  | Safe Agent Platform |
| `GET` | `/api/safe-platform/proposals` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/proposals` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/proposals/execute` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/proposals/validate` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/proposals/{proposal_id}/checkpoint` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/proposals/{proposal_id}/rollback` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/research/request` | JWT |  | Safe Agent Platform |
| `GET` | `/api/safe-platform/supervisor/tasks` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/supervisor/tasks` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/supervisor/tasks/delegate` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/supervisor/tasks/execute` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/supervisor/tasks/plan` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/supervisor/tasks/{task_id}/approve` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/supervisor/tasks/{task_id}/cancel` | JWT |  | Safe Agent Platform |
| `POST` | `/api/safe-platform/upgrades/propose` | JWT |  | Safe Agent Platform |
| `GET` | `/api/scanner/criteria` | JWT |  | Market Scanner |
| `POST` | `/api/scanner/criteria` | JWT |  | Market Scanner |
| `DELETE` | `/api/scanner/criteria` | JWT |  | Market Scanner |
| `GET` | `/api/scanner/opportunities` | JWT |  | Market Scanner |
| `GET` | `/api/scanner/opportunities/top` | JWT |  | Market Scanner |
| `GET` | `/api/scanner/results` | JWT |  | Market Scanner |
| `GET` | `/api/scanner/results/{symbol}` | JWT |  | Market Scanner |
| `POST` | `/api/scanner/scan` | JWT |  | Market Scanner |
| `GET` | `/api/scanner/stats` | JWT |  | Market Scanner |
| `GET` | `/api/scanner/symbols` | JWT |  | Market Scanner |
| `POST` | `/api/scanner/symbols` | JWT |  | Market Scanner |
| `GET` | `/api/security/alerts` | JWT | Active security alerts | security-dashboard, security-dashboard |
| `GET` | `/api/security/attacks` | JWT | Attack / intrusion log | security-dashboard, security-dashboard |
| `POST` | `/api/security/av/quarantine` | JWT |  | antivirus |
| `POST` | `/api/security/av/reconnect-clamd` | JWT | Re-attempt ClamAV daemon connection | antivirus |
| `POST` | `/api/security/av/scan` | JWT |  | antivirus |
| `GET` | `/api/security/av/status` | JWT |  | antivirus |
| `GET` | `/api/security/av/threats` | JWT |  | antivirus |
| `POST` | `/api/security/block-ip` | JWT | Block an IP address | security-dashboard, security-dashboard |
| `GET` | `/api/security/blocked-ips` | JWT | List blocked IP addresses | security-dashboard, security-dashboard |
| `GET` | `/api/security/fixes` | JWT |  | security-fixes |
| `POST` | `/api/security/fixes/approve` | JWT |  | security-fixes |
| `GET` | `/api/security/fixes/approved` | JWT |  | security-fixes |
| `POST` | `/api/security/fixes/decline` | JWT |  | security-fixes |
| `GET` | `/api/security/fixes/declined` | JWT |  | security-fixes |
| `POST` | `/api/security/fixes/scan` | JWT |  | security-fixes |
| `GET` | `/api/security/fixes/stats` | JWT |  | security-fixes |
| `POST` | `/api/security/heal/baseline/rebuild` | JWT |  | self-healer |
| `GET` | `/api/security/heal/claude-queue` | JWT | Get pending Claude fix queue | self-healer |
| `DELETE` | `/api/security/heal/claude-queue` | JWT | Clear the Claude fix queue | self-healer |
| `GET` | `/api/security/heal/code-analysis/issues` | JWT | Get latest code analysis issues | self-healer |
| `POST` | `/api/security/heal/code-analysis/now` | JWT | Trigger immediate deep code analysis scan | self-healer |
| `POST` | `/api/security/heal/diagnostics/now` | JWT | Trigger immediate full diagnostics run | self-healer |
| `GET` | `/api/security/heal/diagnostics/remediation-log` | JWT | Get diagnostics auto-remediation log | self-healer |
| `GET` | `/api/security/heal/diagnostics/report` | JWT | Get the last diagnostics report | self-healer |
| `GET` | `/api/security/heal/drift` | JWT |  | self-healer |
| `GET` | `/api/security/heal/full-status` | JWT | Complete healer + diagnostics status | self-healer |
| `GET` | `/api/security/heal/log-analysis/issues` | JWT | Get latest log analysis issues | self-healer |
| `POST` | `/api/security/heal/log-analysis/now` | JWT | Trigger immediate log file analysis | self-healer |
| `GET` | `/api/security/heal/patches` | JWT |  | self-healer |
| `POST` | `/api/security/heal/scan/now` | JWT |  | self-healer |
| `GET` | `/api/security/heal/status` | JWT |  | self-healer |
| `GET` | `/api/security/lockdown` | JWT | Lockdown status | security-dashboard, security-dashboard |
| `POST` | `/api/security/lockdown` | JWT | Toggle platform lockdown (admin) | security-dashboard, security-dashboard |
| `POST` | `/api/security/lockdown/clear` | JWT | Clear active lockdown (admin) | security-dashboard, security-dashboard |
| `GET` | `/api/security/status` | JWT | Security system status summary | security-dashboard, security-dashboard |
| `POST` | `/api/security/unblock-ip` | JWT | Unblock an IP address | security-dashboard, security-dashboard |
| `GET` | `/api/sentiment/latest` | None |  | Sentiment |
| `GET` | `/api/settings/accessibility` | JWT |  | Settings Extended, Settings Extended |
| `POST` | `/api/settings/accessibility` | JWT |  | Settings Extended, Settings Extended |
| `GET` | `/api/settings/api-keys` | JWT |  | Settings Extended, Settings Extended |
| `POST` | `/api/settings/api-keys` | JWT |  | Settings Extended, Settings Extended |
| `DELETE` | `/api/settings/api-keys/{key_id}` | JWT |  | Settings Extended, Settings Extended |
| `GET` | `/api/settings/appearance` | JWT | Get appearance settings | Settings |
| `POST` | `/api/settings/appearance` | JWT | Save appearance settings | Settings |
| `GET` | `/api/settings/broker` | JWT | Get broker connection settings | Settings |
| `POST` | `/api/settings/broker` | JWT | Save broker connection settings | Settings |
| `GET` | `/api/settings/integrations` | JWT |  | Settings Extended, Settings Extended |
| `POST` | `/api/settings/integrations` | JWT |  | Settings Extended, Settings Extended |
| `POST` | `/api/settings/integrations/test-webhook` | JWT |  | Settings Extended, Settings Extended |
| `GET` | `/api/settings/notifications` | JWT | Get notification settings | Settings |
| `POST` | `/api/settings/notifications` | JWT | Save notification settings | Settings |
| `GET` | `/api/settings/preferences` | JWT | Get user preferences | Settings |
| `POST` | `/api/settings/preferences` | JWT | Save user preferences | Settings |
| `GET` | `/api/settings/privacy` | JWT |  | Settings Extended, Settings Extended |
| `POST` | `/api/settings/privacy` | JWT |  | Settings Extended, Settings Extended |
| `GET` | `/api/settings/privacy/export` | JWT |  | Settings Extended, Settings Extended |
| `GET` | `/api/settings/trading` | JWT | Get trading preferences | Settings |
| `POST` | `/api/settings/trading` | JWT | Save trading preferences | Settings |
| `GET` | `/api/signals` | JWT | List active signals, optionally filtered by symbol | Signals |
| `GET` | `/api/signals/active` | JWT |  | Signals |
| `GET` | `/api/signals/alerts` | JWT |  | Signals |
| `POST` | `/api/signals/alerts` | JWT |  | Signals |
| `DELETE` | `/api/signals/alerts/{alert_id}` | JWT |  | Signals |
| `GET` | `/api/signals/analytics` | JWT |  | Signals |
| `GET` | `/api/signals/channels` | JWT |  | Signals |
| `GET` | `/api/signals/engine` | JWT |  | Signals |
| `POST` | `/api/signals/generate` | JWT |  | Signals |
| `GET` | `/api/signals/history` | JWT |  | Signals |
| `GET` | `/api/signals/latest` | JWT |  | Signals |
| `GET` | `/api/signals/news` | JWT | Recent news items for a symbol | Signals |
| `GET` | `/api/signals/sentiment` | JWT | Market sentiment for a symbol | Signals |
| `GET` | `/api/signals/summary` | JWT |  | Signals |
| `GET` | `/api/social/copy/active` | JWT | List active copy relationships | Copy Trading |
| `DELETE` | `/api/social/copy/{copy_id}` | JWT | Stop copying a trader | Copy Trading |
| `POST` | `/api/social/copy/{trader_id}` | JWT | Start copying a trader | Copy Trading |
| `GET` | `/api/status` | None | System status (alias for /api/status/json) | Status |
| `GET` | `/api/status/history` | None | 90-day uptime history | Status |
| `GET` | `/api/status/incidents` | None | Recent incident history | Status |
| `GET` | `/api/status/json` | None | Machine-readable system status | Status |
| `GET` | `/api/status/live-trading/gate` | None | Production live trading gate — all 5 checks | Status, Status |
| `GET` | `/api/status/paper-trading` | None | OANDA paper trading run status (simple clock) | Status, Status |
| `GET` | `/api/status/paper-trading/gate` | None | OANDA paper trading phase gate status (Phase 2 / Phase 3) | Status, Status |
| `POST` | `/api/status/paper-trading/gate/fill` | JWT | Record a confirmed OANDA fill into the phase gate | Status, Status |
| `GET` | `/api/status/sharpe-progress` | None | Sharpe SE progress toward N=250 (robust Sharpe threshold) | Status, Status |
| `POST` | `/api/strategies/dynamic/activate` | JWT |  | Dynamic Strategies |
| `GET` | `/api/strategies/dynamic/active` | JWT |  | Dynamic Strategies |
| `POST` | `/api/strategies/dynamic/deactivate` | JWT |  | Dynamic Strategies |
| `GET` | `/api/strategies/dynamic/health` | JWT |  | Dynamic Strategies |
| `GET` | `/api/strategies/dynamic/list` | JWT |  | Dynamic Strategies |
| `POST` | `/api/strategies/dynamic/register` | JWT |  | Dynamic Strategies |
| `GET` | `/api/strategies/dynamic/versions` | JWT |  | Dynamic Strategies |
| `POST` | `/api/strategies/dynamic/{name}/{action_type}` | JWT |  | Dynamic Strategies |
| `GET` | `/api/stream/stats` | None |  | Streaming |
| `GET` | `/api/stream/{symbol}/bars/{timeframe}` | None |  | Streaming |
| `GET` | `/api/stream/{symbol}/ticks` | None |  | Streaming |
| `GET` | `/api/superadmin/alerting/channels` | JWT |  |  |
| `GET` | `/api/superadmin/alerting/fired` | JWT |  |  |
| `GET` | `/api/superadmin/alerting/history` | JWT |  |  |
| `GET` | `/api/superadmin/alerting/prometheus` | JWT |  |  |
| `GET` | `/api/superadmin/alerting/rules` | JWT |  |  |
| `POST` | `/api/superadmin/alerting/rules` | JWT |  |  |
| `PATCH` | `/api/superadmin/alerting/rules/{rule_id}` | JWT |  |  |
| `DELETE` | `/api/superadmin/alerting/rules/{rule_id}` | JWT |  |  |
| `POST` | `/api/superadmin/alerting/rules/{rule_id}/silence` | JWT |  |  |
| `POST` | `/api/superadmin/alerting/rules/{rule_id}/test` | JWT |  |  |
| `GET` | `/api/superadmin/audit` | JWT |  |  |
| `GET` | `/api/superadmin/audit/export` | JWT |  |  |
| `POST` | `/api/superadmin/auto-healing/approve/{patch_index}` | JWT |  |  |
| `GET` | `/api/superadmin/auto-healing/audit-log` | JWT |  |  |
| `POST` | `/api/superadmin/auto-healing/baseline/rebuild` | JWT |  |  |
| `GET` | `/api/superadmin/auto-healing/config` | JWT |  |  |
| `PUT` | `/api/superadmin/auto-healing/config` | JWT |  |  |
| `GET` | `/api/superadmin/auto-healing/drift` | JWT |  |  |
| `GET` | `/api/superadmin/auto-healing/patches` | JWT |  |  |
| `GET` | `/api/superadmin/auto-healing/pending-approval` | JWT |  |  |
| `GET` | `/api/superadmin/auto-healing/quarantine` | JWT |  |  |
| `GET` | `/api/superadmin/auto-healing/status` | JWT |  |  |
| `GET` | `/api/superadmin/auto-healing/tests/index` | JWT |  |  |
| `POST` | `/api/superadmin/auto-healing/tests/reindex` | JWT |  |  |
| `POST` | `/api/superadmin/auto-healing/tests/run` | JWT |  |  |
| `GET` | `/api/superadmin/brokers/health` | JWT |  |  |
| `GET` | `/api/superadmin/brokers/routing` | JWT |  |  |
| `PATCH` | `/api/superadmin/brokers/routing` | JWT |  |  |
| `GET` | `/api/superadmin/brokers/tca` | JWT |  |  |
| `POST` | `/api/superadmin/brokers/{broker_id}/disconnect` | JWT |  |  |
| `POST` | `/api/superadmin/brokers/{broker_id}/reconnect` | JWT |  |  |
| `GET` | `/api/superadmin/compliance/aml/alerts` | JWT |  |  |
| `PATCH` | `/api/superadmin/compliance/aml/alerts/{alert_id}` | JWT |  |  |
| `GET` | `/api/superadmin/compliance/audit-trail` | JWT |  |  |
| `GET` | `/api/superadmin/compliance/audit-trail/export` | JWT |  |  |
| `GET` | `/api/superadmin/compliance/kyc` | JWT |  |  |
| `POST` | `/api/superadmin/compliance/kyc/{user_id}/approve` | JWT |  |  |
| `POST` | `/api/superadmin/compliance/kyc/{user_id}/reject` | JWT |  |  |
| `GET` | `/api/superadmin/compliance/regulatory/reports` | JWT |  |  |
| `POST` | `/api/superadmin/compliance/regulatory/trigger` | JWT |  |  |
| `GET` | `/api/superadmin/compliance/sanctions` | JWT |  |  |
| `POST` | `/api/superadmin/compliance/sanctions/{hit_id}/clear` | JWT |  |  |
| `GET` | `/api/superadmin/diagnostics/checks` | JWT |  |  |
| `POST` | `/api/superadmin/diagnostics/checks/{check_name}/run` | JWT |  |  |
| `POST` | `/api/superadmin/diagnostics/remediate` | JWT |  |  |
| `GET` | `/api/superadmin/diagnostics/remediation-log` | JWT |  |  |
| `GET` | `/api/superadmin/diagnostics/report` | JWT |  |  |
| `GET` | `/api/superadmin/diagnostics/results` | JWT |  |  |
| `POST` | `/api/superadmin/diagnostics/run` | JWT |  |  |
| `GET` | `/api/superadmin/diagnostics/summary` | JWT |  |  |
| `GET` | `/api/superadmin/engine/config` | JWT |  |  |
| `PATCH` | `/api/superadmin/engine/config` | JWT |  |  |
| `POST` | `/api/superadmin/engine/kill-switch` | JWT |  |  |
| `GET` | `/api/superadmin/engine/metrics` | JWT |  |  |
| `POST` | `/api/superadmin/engine/pause` | JWT |  |  |
| `POST` | `/api/superadmin/engine/resume` | JWT |  |  |
| `GET` | `/api/superadmin/engine/status` | JWT |  |  |
| `GET` | `/api/superadmin/feature-flags` | JWT |  |  |
| `GET` | `/api/superadmin/feature-flags/overrides/{target_user_id}` | JWT |  |  |
| `PATCH` | `/api/superadmin/feature-flags/overrides/{target_user_id}/{flag_name}` | JWT |  |  |
| `PATCH` | `/api/superadmin/feature-flags/{flag_name}` | JWT |  |  |
| `GET` | `/api/superadmin/financial/affiliates` | JWT |  |  |
| `GET` | `/api/superadmin/financial/chargebacks` | JWT |  |  |
| `PATCH` | `/api/superadmin/financial/chargebacks/{chargeback_id}` | JWT |  |  |
| `GET` | `/api/superadmin/financial/fee-config` | JWT |  |  |
| `PATCH` | `/api/superadmin/financial/fee-config` | JWT |  |  |
| `GET` | `/api/superadmin/financial/payments` | JWT |  |  |
| `POST` | `/api/superadmin/financial/payments/{payment_id}/refund` | JWT |  |  |
| `GET` | `/api/superadmin/financial/payouts` | JWT |  |  |
| `GET` | `/api/superadmin/financial/reconciliation` | JWT |  |  |
| `POST` | `/api/superadmin/financial/reconciliation/run` | JWT |  |  |
| `PATCH` | `/api/superadmin/financial/reconciliation/{recon_id}` | JWT |  |  |
| `GET` | `/api/superadmin/financial/refund-policy` | JWT |  |  |
| `PUT` | `/api/superadmin/financial/refund-policy` | JWT |  |  |
| `GET` | `/api/superadmin/financial/revenue` | JWT |  |  |
| `GET` | `/api/superadmin/financial/subscriptions` | JWT |  |  |
| `GET` | `/api/superadmin/financial/tax-reports` | JWT |  |  |
| `POST` | `/api/superadmin/financial/tax-reports` | JWT |  |  |
| `PATCH` | `/api/superadmin/financial/tax-reports/{report_id}` | JWT |  |  |
| `GET` | `/api/superadmin/financial/wallets` | JWT |  |  |
| `GET` | `/api/superadmin/gdpr/consent-log` | JWT |  |  |
| `GET` | `/api/superadmin/gdpr/requests` | JWT |  |  |
| `POST` | `/api/superadmin/gdpr/requests/{req_id}/process` | JWT |  |  |
| `GET` | `/api/superadmin/gdpr/retention-policies` | JWT |  |  |
| `PATCH` | `/api/superadmin/gdpr/retention-policies` | JWT |  |  |
| `POST` | `/api/superadmin/gdpr/users/{user_id}/erase` | JWT |  |  |
| `POST` | `/api/superadmin/gdpr/users/{user_id}/export` | JWT |  |  |
| `GET` | `/api/superadmin/health-engine/history` | JWT |  |  |
| `POST` | `/api/superadmin/health-engine/probe/{name}` | JWT |  |  |
| `GET` | `/api/superadmin/health-engine/probes` | JWT |  |  |
| `POST` | `/api/superadmin/health-engine/register` | JWT |  |  |
| `POST` | `/api/superadmin/health-engine/run` | JWT |  |  |
| `GET` | `/api/superadmin/health-engine/status` | JWT |  |  |
| `GET` | `/api/superadmin/infra/cache` | JWT |  |  |
| `POST` | `/api/superadmin/infra/cache/flush` | JWT |  |  |
| `GET` | `/api/superadmin/infra/db` | JWT |  |  |
| `GET` | `/api/superadmin/infra/health` | JWT |  |  |
| `GET` | `/api/superadmin/infra/queues` | JWT |  |  |
| `GET` | `/api/superadmin/logs` | JWT |  |  |
| `GET` | `/api/superadmin/logs/export` | JWT |  |  |
| `GET` | `/api/superadmin/logs/levels` | JWT |  |  |
| `PATCH` | `/api/superadmin/logs/levels` | JWT |  |  |
| `GET` | `/api/superadmin/ml/ab-tests` | JWT |  |  |
| `POST` | `/api/superadmin/ml/deploy` | JWT |  |  |
| `GET` | `/api/superadmin/ml/drift` | JWT |  |  |
| `GET` | `/api/superadmin/ml/explainability` | JWT |  |  |
| `GET` | `/api/superadmin/ml/metrics` | JWT |  |  |
| `GET` | `/api/superadmin/ml/models` | JWT |  |  |
| `POST` | `/api/superadmin/ml/retrain/{model_name}` | JWT |  |  |
| `POST` | `/api/superadmin/ml/rl/control` | JWT |  |  |
| `GET` | `/api/superadmin/ml/rl/status` | JWT |  |  |
| `POST` | `/api/superadmin/ml/rollback/{model_name}` | JWT |  |  |
| `GET` | `/api/superadmin/ml/status` | JWT |  |  |
| `GET` | `/api/superadmin/ml/training-jobs` | JWT |  |  |
| `POST` | `/api/superadmin/nuclear/halt` | JWT |  |  |
| `POST` | `/api/superadmin/nuclear/hedge/activate` | JWT |  |  |
| `POST` | `/api/superadmin/nuclear/hedge/deactivate` | JWT |  |  |
| `GET` | `/api/superadmin/nuclear/log` | JWT |  |  |
| `POST` | `/api/superadmin/nuclear/resume` | JWT |  |  |
| `POST` | `/api/superadmin/nuclear/risk-override` | JWT |  |  |
| `GET` | `/api/superadmin/nuclear/status` | JWT |  |  |
| `GET` | `/api/superadmin/overview` | JWT |  |  |
| `POST` | `/api/superadmin/platform/broadcast` | JWT |  |  |
| `GET` | `/api/superadmin/platform/config` | JWT |  |  |
| `PATCH` | `/api/superadmin/platform/config` | JWT |  |  |
| `PUT` | `/api/superadmin/platform/config/full` | JWT |  |  |
| `GET` | `/api/superadmin/platform/config/validate` | JWT |  |  |
| `POST` | `/api/superadmin/platform/maintenance` | JWT |  |  |
| `POST` | `/api/superadmin/platform/test-smtp` | JWT |  |  |
| `GET` | `/api/superadmin/rate-limits` | JWT |  |  |
| `POST` | `/api/superadmin/rate-limits` | JWT |  |  |
| `GET` | `/api/superadmin/rate-limits/rules` | JWT |  |  |
| `POST` | `/api/superadmin/rate-limits/rules` | JWT |  |  |
| `PATCH` | `/api/superadmin/rate-limits/rules/{rule_id}` | JWT |  |  |
| `DELETE` | `/api/superadmin/rate-limits/rules/{rule_id}` | JWT |  |  |
| `GET` | `/api/superadmin/rate-limits/stats` | JWT |  |  |
| `GET` | `/api/superadmin/rate-limits/violations` | JWT |  |  |
| `PATCH` | `/api/superadmin/rate-limits/{rule_id}` | JWT |  |  |
| `DELETE` | `/api/superadmin/rate-limits/{rule_id}` | JWT |  |  |
| `POST` | `/api/superadmin/rate-limits/{rule_id}/reset` | JWT |  |  |
| `GET` | `/api/superadmin/reliability/components` | JWT |  |  |
| `GET` | `/api/superadmin/reliability/env` | JWT |  |  |
| `GET` | `/api/superadmin/reliability/history` | JWT |  |  |
| `POST` | `/api/superadmin/reliability/history/record` | JWT |  |  |
| `GET` | `/api/superadmin/reliability/metrics` | JWT |  |  |
| `POST` | `/api/superadmin/reliability/probe` | JWT |  |  |
| `GET` | `/api/superadmin/reliability/routes` | JWT |  |  |
| `POST` | `/api/superadmin/reliability/self-test` | JWT |  |  |
| `GET` | `/api/superadmin/reliability/status` | JWT |  |  |
| `POST` | `/api/superadmin/reliability/trace/test` | JWT |  |  |
| `GET` | `/api/superadmin/reliability/traces` | JWT |  |  |
| `POST` | `/api/superadmin/reliability/validate-toggle` | JWT |  |  |
| `GET` | `/api/superadmin/reliability/validate/{setting_key}` | JWT |  |  |
| `GET` | `/api/superadmin/reporting/reports` | JWT |  |  |
| `POST` | `/api/superadmin/reporting/reports/generate` | JWT |  |  |
| `DELETE` | `/api/superadmin/reporting/reports/{report_id}` | JWT |  |  |
| `GET` | `/api/superadmin/reporting/reports/{report_id}/download` | JWT |  |  |
| `GET` | `/api/superadmin/reporting/templates` | JWT |  |  |
| `GET` | `/api/superadmin/reports` | JWT |  |  |
| `POST` | `/api/superadmin/reports/generate` | JWT |  |  |
| `DELETE` | `/api/superadmin/reports/{report_id}` | JWT |  |  |
| `GET` | `/api/superadmin/reports/{report_id}/download` | JWT |  |  |
| `GET` | `/api/superadmin/risk/circuit-breakers` | JWT |  |  |
| `POST` | `/api/superadmin/risk/circuit-breakers/{name}/open` | JWT |  |  |
| `POST` | `/api/superadmin/risk/circuit-breakers/{name}/reset` | JWT |  |  |
| `GET` | `/api/superadmin/risk/drawdown` | JWT |  |  |
| `GET` | `/api/superadmin/risk/prop-breaches` | JWT |  |  |
| `GET` | `/api/superadmin/risk/stress-tests` | JWT |  |  |
| `POST` | `/api/superadmin/risk/stress-tests/run` | JWT |  |  |
| `GET` | `/api/superadmin/risk/var` | JWT |  |  |
| `GET` | `/api/superadmin/security-infra/antivirus` | JWT |  |  |
| `POST` | `/api/superadmin/security-infra/antivirus/scan` | JWT |  |  |
| `GET` | `/api/superadmin/security-infra/api-keys` | JWT |  |  |
| `POST` | `/api/superadmin/security-infra/api-keys/{key_id}/revoke` | JWT |  |  |
| `GET` | `/api/superadmin/security-infra/certificates` | JWT |  |  |
| `GET` | `/api/superadmin/security-infra/hsm` | JWT |  |  |
| `POST` | `/api/superadmin/security-infra/hsm/keys/{key_id}/rotate` | JWT |  |  |
| `GET` | `/api/superadmin/security-infra/log` | JWT |  |  |
| `GET` | `/api/superadmin/security-infra/self-healer` | JWT |  |  |
| `POST` | `/api/superadmin/security-infra/self-healer/scan` | JWT |  |  |
| `GET` | `/api/superadmin/security-infra/status` | JWT |  |  |
| `GET` | `/api/superadmin/security-infra/waf/rules` | JWT |  |  |
| `POST` | `/api/superadmin/security-infra/waf/rules` | JWT |  |  |
| `POST` | `/api/superadmin/security/block-ip` | JWT |  |  |
| `GET` | `/api/superadmin/security/blocked-ips` | JWT |  |  |
| `DELETE` | `/api/superadmin/security/blocked-ips/{ip}` | JWT |  |  |
| `GET` | `/api/superadmin/security/events` | JWT |  |  |
| `GET` | `/api/superadmin/security/sessions` | JWT |  |  |
| `DELETE` | `/api/superadmin/security/sessions/user/{target_user_id}` | JWT |  |  |
| `DELETE` | `/api/superadmin/security/sessions/{session_id}` | JWT |  |  |
| `GET` | `/api/superadmin/security/threat-intel` | JWT |  |  |
| `GET` | `/api/superadmin/system-health/backups` | JWT |  |  |
| `POST` | `/api/superadmin/system-health/backups/trigger` | JWT |  |  |
| `GET` | `/api/superadmin/system-health/dependencies` | JWT |  |  |
| `GET` | `/api/superadmin/system-health/jobs` | JWT |  |  |
| `POST` | `/api/superadmin/system-health/jobs/{job_id}/run` | JWT |  |  |
| `GET` | `/api/superadmin/system-health/resources` | JWT |  |  |
| `GET` | `/api/superadmin/system-health/services` | JWT |  |  |
| `GET` | `/api/superadmin/system/api-keys` | JWT |  |  |
| `DELETE` | `/api/superadmin/system/api-keys/{key_id}` | JWT |  |  |
| `GET` | `/api/superadmin/system/backups` | JWT |  |  |
| `POST` | `/api/superadmin/system/backups/trigger` | JWT |  |  |
| `GET` | `/api/superadmin/system/jobs` | JWT |  |  |
| `POST` | `/api/superadmin/system/jobs/{job_id}/pause` | JWT |  |  |
| `POST` | `/api/superadmin/system/jobs/{job_id}/resume` | JWT |  |  |
| `POST` | `/api/superadmin/system/jobs/{job_id}/trigger` | JWT |  |  |
| `GET` | `/api/superadmin/system/resources` | JWT |  |  |
| `GET` | `/api/superadmin/system/services` | JWT |  |  |
| `GET` | `/api/superadmin/trading/accounts` | JWT | Every account with an open book (operator view) |  |
| `GET` | `/api/superadmin/trading/accounts/{account_user_id}` | JWT | One named account's positions and balance (operator view) |  |
| `GET` | `/api/superadmin/trading/positions` | JWT | Every open position across all accounts (operator view) |  |
| `GET` | `/api/superadmin/users` | JWT |  |  |
| `POST` | `/api/superadmin/users/bulk/ban` | JWT |  |  |
| `POST` | `/api/superadmin/users/bulk/export` | JWT |  |  |
| `POST` | `/api/superadmin/users/bulk/unban` | JWT |  |  |
| `GET` | `/api/superadmin/users/{user_id}` | JWT |  |  |
| `PATCH` | `/api/superadmin/users/{user_id}` | JWT |  |  |
| `DELETE` | `/api/superadmin/users/{user_id}` | JWT |  |  |
| `GET` | `/api/superadmin/users/{user_id}/activity` | JWT |  |  |
| `POST` | `/api/superadmin/users/{user_id}/ban` | JWT |  |  |
| `POST` | `/api/superadmin/users/{user_id}/impersonate` | JWT |  |  |
| `PATCH` | `/api/superadmin/users/{user_id}/plan` | JWT |  |  |
| `POST` | `/api/superadmin/users/{user_id}/reset-password` | JWT |  |  |
| `PATCH` | `/api/superadmin/users/{user_id}/role` | JWT |  |  |
| `POST` | `/api/superadmin/users/{user_id}/unban` | JWT |  |  |
| `GET` | `/api/superadmin/whitelabel/tenants` | JWT |  |  |
| `POST` | `/api/superadmin/whitelabel/tenants` | JWT |  |  |
| `GET` | `/api/superadmin/whitelabel/tenants/{tenant_id}` | JWT |  |  |
| `PATCH` | `/api/superadmin/whitelabel/tenants/{tenant_id}` | JWT |  |  |
| `DELETE` | `/api/superadmin/whitelabel/tenants/{tenant_id}` | JWT |  |  |
| `POST` | `/api/superadmin/whitelabel/tenants/{tenant_id}/activate` | JWT |  |  |
| `GET` | `/api/superadmin/whitelabel/tenants/{tenant_id}/api-keys` | JWT |  |  |
| `POST` | `/api/superadmin/whitelabel/tenants/{tenant_id}/api-keys/rotate` | JWT |  |  |
| `POST` | `/api/superadmin/whitelabel/tenants/{tenant_id}/suspend` | JWT |  |  |
| `GET` | `/api/superadmin/whitelabel/tenants/{tenant_id}/usage` | JWT |  |  |
| `GET` | `/api/tca/alerts` | JWT |  | tca |
| `GET` | `/api/tca/records` | JWT |  | tca |
| `DELETE` | `/api/tca/records` | JWT |  | tca |
| `GET` | `/api/tca/report` | JWT |  | tca |
| `GET` | `/api/tca/report/{broker}` | JWT |  | tca |
| `GET` | `/api/tca/stats` | JWT |  | tca |
| `GET` | `/api/teams` | JWT |  | Teams |
| `POST` | `/api/teams` | JWT |  | Teams |
| `GET` | `/api/teams/` | JWT |  | Teams |
| `POST` | `/api/teams/` | JWT |  | Teams |
| `POST` | `/api/teams/invitations/accept` | JWT |  | Teams |
| `GET` | `/api/teams/{team_id}` | JWT |  | Teams |
| `DELETE` | `/api/teams/{team_id}` | JWT |  | Teams |
| `GET` | `/api/teams/{team_id}/activity` | JWT |  | Teams |
| `POST` | `/api/teams/{team_id}/invite` | JWT |  | Teams |
| `POST` | `/api/teams/{team_id}/members` | JWT |  | Teams |
| `PATCH` | `/api/teams/{team_id}/members/{user_id}` | JWT |  | Teams |
| `DELETE` | `/api/teams/{team_id}/members/{user_id}` | JWT |  | Teams |
| `GET` | `/api/teams/{team_id}/members/{user_id}/permissions` | JWT |  | Teams |
| `PUT` | `/api/teams/{team_id}/members/{user_id}/role` | JWT |  | Teams |
| `GET` | `/api/teams/{team_id}/performance` | JWT |  | Teams |
| `GET` | `/api/timesales/stats` | None |  | Time & Sales |
| `GET` | `/api/timesales/{symbol}/aggressor` | None |  | Time & Sales |
| `GET` | `/api/timesales/{symbol}/histogram` | None |  | Time & Sales |
| `GET` | `/api/timesales/{symbol}/large` | None |  | Time & Sales |
| `GET` | `/api/timesales/{symbol}/recent` | None |  | Time & Sales |
| `GET` | `/api/timesales/{symbol}/statistics` | None |  | Time & Sales |
| `GET` | `/api/timesales/{symbol}/velocity` | None |  | Time & Sales |
| `GET` | `/api/tracing/config` | JWT | Get current OpenTelemetry configuration | Observability |
| `GET` | `/api/tracing/spans` | JWT | Return last 100 spans from in-memory ring buffer | Observability |
| `POST` | `/api/tracing/test` | JWT | Emit a test span and return its trace ID | Observability |
| `GET` | `/api/trading/account` | JWT | Get full AccountMetrics snapshot | Trading |
| `POST` | `/api/trading/ai-analysis` | JWT | AI chart-click analysis | Trading |
| `GET` | `/api/trading/balance` | JWT | Account balance (alias for /account) | Trading |
| `GET` | `/api/trading/brain-state` | JWT |  | Trading |
| `GET` | `/api/trading/depth/{symbol}` | JWT | Get order book depth (bid/ask ladder) for a symbol | Trading |
| `POST` | `/api/trading/emergency-stop` | JWT |  | Trading |
| `GET` | `/api/trading/equity-curve` | JWT | Equity curve data points | Trading |
| `GET` | `/api/trading/history` | JWT | Trade history (alias for /trades) | Trading |
| `GET` | `/api/trading/levels` | JWT | Support and resistance levels for a symbol | Trading |
| `GET` | `/api/trading/microstructure` | JWT | Market microstructure snapshot | Trading |
| `GET` | `/api/trading/ohlcv/{symbol:path}` | JWT | Get OHLCV candlestick data for a symbol | Trading |
| `GET` | `/api/trading/orders` | JWT | List open and recent orders | Trading |
| `POST` | `/api/trading/orders` | JWT | Place a market/limit/stop order | Trading |
| `PATCH` | `/api/trading/orders/{order_id}` | JWT | Modify price, quantity, SL, or TP on a pending order | Trading |
| `DELETE` | `/api/trading/orders/{order_id}` | JWT | Cancel a pending or open order | Trading |
| `POST` | `/api/trading/paper/start` | JWT |  | Trading |
| `POST` | `/api/trading/paper/stop` | JWT |  | Trading |
| `GET` | `/api/trading/patterns` | JWT | Chart patterns for a symbol | Trading |
| `GET` | `/api/trading/performance/summary` | JWT |  |  |
| `GET` | `/api/trading/performance/{strategy_id}` | JWT |  |  |
| `POST` | `/api/trading/position-size` | JWT |  |  |
| `GET` | `/api/trading/positions` | JWT |  | Trading |
| `DELETE` | `/api/trading/positions` | JWT | Close all open positions | Trading |
| `PATCH` | `/api/trading/positions/{position_id}` | JWT | Modify stop-loss, take-profit, or trailing stop on an open position | Trading |
| `DELETE` | `/api/trading/positions/{position_id}` | JWT | Close a specific open position | Trading |
| `POST` | `/api/trading/positions/{position_id}/hedge` | JWT | Open a hedge (opposite-side) order for an existing position | Trading |
| `POST` | `/api/trading/positions/{position_id}/partial-close` | JWT | Partially close an open position by lot size | Trading |
| `GET` | `/api/trading/prices` | JWT | Get current bid/ask prices for all tracked symbols | Trading |
| `GET` | `/api/trading/regime` | JWT | Current market regime and active strategy | Trading |
| `GET` | `/api/trading/regime/history` | JWT | Recent regime transition history | Trading |
| `GET` | `/api/trading/risk` | JWT | Risk metrics snapshot | Trading |
| `GET` | `/api/trading/risk-metrics` | JWT |  |  |
| `GET` | `/api/trading/signals` | JWT | Active trading signals from the signal engine | Trading |
| `GET` | `/api/trading/strategies` | JWT |  |  |
| `POST` | `/api/trading/strategies` | JWT |  |  |
| `GET` | `/api/trading/strategies/{strategy_id}` | JWT |  |  |
| `DELETE` | `/api/trading/strategies/{strategy_id}` | JWT |  |  |
| `POST` | `/api/trading/strategies/{strategy_id}/start` | JWT |  |  |
| `POST` | `/api/trading/strategies/{strategy_id}/stop` | JWT |  |  |
| `GET` | `/api/trading/stress-test` | JWT | Run historical stress scenarios on current position | Trading |
| `GET` | `/api/trading/symbol/{symbol}` | JWT | Get instrument specification for a single symbol | Trading |
| `GET` | `/api/trading/symbols` | JWT | List all tradeable instruments | Trading |
| `GET` | `/api/trading/symbols/search` | JWT | Search instruments by symbol or description | Trading |
| `GET` | `/api/trading/trades` | JWT |  | Trading |
| `GET` | `/api/trading/trades/export` | JWT |  | Trading |
| `GET` | `/api/trading/trendlines` | JWT | Trendlines for a symbol | Trading |
| `GET` | `/api/transparency/audit` | JWT |  | Transparency |
| `GET` | `/api/transparency/audit-log` | JWT |  | Transparency |
| `GET` | `/api/transparency/best-execution` | JWT | Best-execution report (alias) | Transparency |
| `GET` | `/api/transparency/decisions` | None |  | Transparency |
| `POST` | `/api/transparency/executions` | JWT |  | Transparency |
| `GET` | `/api/transparency/explain/{trade_id}` | None |  | Transparency |
| `GET` | `/api/transparency/latency/trend` | JWT |  | Transparency |
| `GET` | `/api/transparency/orders/{order_id}` | JWT |  | Transparency |
| `GET` | `/api/transparency/report` | JWT |  | Transparency |
| `GET` | `/api/transparency/slippage` | JWT | Slippage distribution (alias) | Transparency |
| `GET` | `/api/transparency/slippage/distribution` | JWT |  | Transparency |
| `GET` | `/api/transparency/statement` | None |  | Transparency |
| `GET` | `/api/transparency/stats` | None |  | Transparency |
| `GET` | `/api/transparency/summary` | JWT | Execution transparency summary | Transparency |
| `GET` | `/api/transparency/venues` | JWT | Trading venue performance | Transparency |
| `GET` | `/api/tutorials` | JWT | List the tutorial catalogue with per-episode lock flags | Tutorials |
| `GET` | `/api/tutorials/{episode}` | JWT | Get one episode (video_url gated by plan) | Tutorials |
| `GET` | `/api/voice/status` | JWT |  | Voice |
| `POST` | `/api/voice/stt` | JWT |  | Voice |
| `POST` | `/api/voice/tts` | JWT |  | Voice |
| `GET` | `/api/watchlist` | JWT |  | Watchlist |
| `PUT` | `/api/watchlist/order` | JWT | Reorder watchlist symbols (PUT alias for PATCH /order) | Watchlist |
| `PATCH` | `/api/watchlist/order` | JWT |  | Watchlist |
| `GET` | `/api/watchlist/prices` | JWT |  | Watchlist |
| `POST` | `/api/watchlist/{symbol}` | JWT |  | Watchlist |
| `DELETE` | `/api/watchlist/{symbol}` | JWT |  | Watchlist |
| `POST` | `/api/webhooks/tradingview` | None | Receive TradingView alert and ingest as trading signal | Webhooks |
| `GET` | `/api/whitelabel/features` | JWT |  | Whitelabel |
| `GET` | `/api/whitelabel/tenants` | JWT |  | Whitelabel |
| `POST` | `/api/whitelabel/tenants` | JWT |  | Whitelabel |
| `GET` | `/api/whitelabel/tenants/{tenant_id}` | JWT |  | Whitelabel |
| `PATCH` | `/api/whitelabel/tenants/{tenant_id}` | JWT |  | Whitelabel |
| `DELETE` | `/api/whitelabel/tenants/{tenant_id}` | JWT |  | Whitelabel |
| `POST` | `/api/whitelabel/tenants/{tenant_id}/activate` | JWT |  | Whitelabel |
| `POST` | `/api/whitelabel/tenants/{tenant_id}/api-key` | JWT |  | Whitelabel |
| `POST` | `/api/whitelabel/tenants/{tenant_id}/features/{feature}` | JWT |  | Whitelabel |
| `DELETE` | `/api/whitelabel/tenants/{tenant_id}/features/{feature}` | JWT |  | Whitelabel |
| `GET` | `/api/whitelabel/tenants/{tenant_id}/preview` | JWT |  | Whitelabel |
| `POST` | `/api/whitelabel/tenants/{tenant_id}/suspend` | JWT |  | Whitelabel |
| `POST` | `/kyc/applicants` | JWT |  | kyc |
| `GET` | `/kyc/applicants/{applicant_id}/status` | JWT |  | kyc |
| `POST` | `/kyc/sanctions/screen` | JWT |  | kyc |
| `GET` | `/kyc/status` | JWT |  | kyc |
| `POST` | `/kyc/webhooks/onfido` | None |  | kyc |
| `POST` | `/kyc/webhooks/sumsub` | None |  | kyc |
| `GET` | `/mobile/api/v2/account` | JWT |  | Mobile, Account |
| `POST` | `/mobile/api/v2/auth/login` | None |  | Mobile, Auth |
| `POST` | `/mobile/api/v2/auth/refresh` | None |  | Mobile, Auth |
| `POST` | `/mobile/api/v2/auth/register` | None |  | Mobile, Auth |
| `GET` | `/mobile/api/v2/news` | JWT |  | Mobile, News |
| `GET` | `/mobile/api/v2/notifications/preferences` | JWT |  | Mobile, Notifications |
| `POST` | `/mobile/api/v2/notifications/preferences` | JWT |  | Mobile, Notifications |
| `POST` | `/mobile/api/v2/orders` | JWT |  | Mobile, Trading |
| `GET` | `/mobile/api/v2/performance` | JWT |  | Mobile, Analytics |
| `GET` | `/mobile/api/v2/quotes/{symbol}` | JWT |  | Mobile, Trading |
| `GET` | `/mobile/api/v2/trades` | JWT |  | Mobile, Trading |
| `POST` | `/mobile/api/v2/trades/{trade_id}/close` | JWT |  | Mobile, Trading |
| `GET` | `/mobile/health` | None |  | Mobile, Health |
| `GET` | `/superadmin/ai-operations/permissions` | JWT |  | ai-operations |
| `POST` | `/superadmin/ai-operations/permissions/review` | JWT |  | ai-operations |
| `POST` | `/superadmin/ai-operations/recovery/assess` | JWT |  | ai-operations |
| `GET` | `/superadmin/ai-operations/recovery/latest` | JWT |  | ai-operations |
| `GET` | `/ws/live/stats` | None |  | WebSocket Live |
