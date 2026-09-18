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
| `GET` | `/api/2fa/backup-codes` | JWT | Generate 8 one-time backup codes for account recovery. | Two-Factor Auth |
| `POST` | `/api/2fa/backup-codes/regenerate` | JWT | Regenerate 8 one-time backup codes, replacing any existing ones. | Two-Factor Auth |
| `POST` | `/api/2fa/disable` | JWT | Disable 2FA after verifying the current TOTP code or a backup code. | Two-Factor Auth |
| `POST` | `/api/2fa/setup` | JWT | Generate a TOTP secret and QR code URI for the authenticated user. | Two-Factor Auth |
| `GET` | `/api/2fa/status` | JWT | Return whether 2FA is enabled and how many backup codes remain. | Two-Factor Auth |
| `POST` | `/api/2fa/verify` | JWT | Verify a TOTP code and activate 2FA for the authenticated user. | Two-Factor Auth |
| `GET` | `/api/accounts/sub-accounts` | JWT | List all sub-accounts owned by the current user. | Accounts |
| `POST` | `/api/accounts/sub-accounts` | JWT | Create a new sub-account. | Accounts |
| `GET` | `/api/accounts/sub-accounts/{account_id}` | JWT | Get a specific sub-account | Accounts |
| `PATCH` | `/api/accounts/sub-accounts/{account_id}` | JWT | Update sub-account fields. | Accounts |
| `DELETE` | `/api/accounts/sub-accounts/{account_id}` | JWT | Delete a sub-account. Cannot delete the last active account. | Accounts |
| `POST` | `/api/accounts/sub-accounts/{account_id}/transfer` | JWT | Transfer balance between sub-accounts | Accounts |
| `GET` | `/api/accounts/teams` | JWT | List teams the current user belongs to. | Accounts |
| `POST` | `/api/accounts/teams` | JWT | Create a new team. Creator is added as owner member. | Accounts |
| `POST` | `/api/accounts/teams/{team_id}/members` | JWT | Invite a member to a team. Requires owner role. | Accounts |
| `PATCH` | `/api/accounts/teams/{team_id}/members/{member_id}` | JWT | Change a team member's role. Requires owner role. | Accounts |
| `DELETE` | `/api/accounts/teams/{team_id}/members/{member_id}` | JWT | Remove a member from a team. Requires owner role. | Accounts |
| `GET` | `/api/admin/` | JWT | Admin dashboard. Requires: role >= 'admin'. | Admin |
| `GET` | `/api/admin/activity` | JWT | All user activity logs. Requires: role >= 'admin'. | Admin |
| `GET` | `/api/admin/alerts` | JWT | Active admin alerts | Admin |
| `GET` | `/api/admin/audit-log` | JWT | Paginated audit log | Admin |
| `GET` | `/api/admin/audit-log/export` | JWT | Export audit log as CSV | Admin |
| `POST` | `/api/admin/backup/trigger` | JWT | Trigger a system backup | Admin |
| `POST` | `/api/admin/broadcast` | JWT | Broadcast a platform-wide message to all users | Admin |
| `GET` | `/api/admin/dashboard-data` | JWT | Full system state. Requires: role >= 'admin'. | Admin |
| `GET` | `/api/admin/feature-flags` | JWT | Return all feature flags with their current state and metadata. Admin only. | Platform, Platform |
| `POST` | `/api/admin/feature-flags/{flag_name}/disable` | JWT | Disable a feature flag at runtime. Admin only. | Platform, Platform |
| `POST` | `/api/admin/feature-flags/{flag_name}/enable` | JWT | Enable a feature flag at runtime (sets env var for this process). Admin only. | Platform, Platform |
| `POST` | `/api/admin/feature-flags/{flag_name}/override` | JWT | Set a per-user feature flag override (e.g. give beta users early access). Admin only. | Platform, Platform |
| `POST` | `/api/admin/kill-switch/global` | JWT |  | Settings Extended, Settings Extended |
| `POST` | `/api/admin/kyc/decide` | JWT | Approve, reject, or request more info for a KYC submission. | Admin |
| `GET` | `/api/admin/kyc/pending` | JWT | List users with pending KYC submissions. Requires: role >= 'admin'. | Admin |
| `GET` | `/api/admin/kyc/{user_id}` | JWT | Get KYC status for a specific user. Requires: role >= 'admin'. | Admin |
| `GET` | `/api/admin/logs` | JWT | Recent activity log. Requires: role >= 'admin'. | Admin |
| `GET` | `/api/admin/maintenance` | JWT | Get maintenance mode status | Admin |
| `POST` | `/api/admin/maintenance` | JWT | Toggle maintenance mode | Admin |
| `GET` | `/api/admin/monitoring` | JWT | Monitoring page. Requires: role >= 'admin'. | Admin |
| `GET` | `/api/admin/overview` | JWT | Admin overview KPIs | Admin |
| `POST` | `/api/admin/pause` | JWT | Pause all automated trading | Admin |
| `POST` | `/api/admin/resume` | JWT | Resume automated trading | Admin |
| `POST` | `/api/admin/risk-settings` | JWT | Update live risk management parameters | Admin |
| `GET` | `/api/admin/settings` | JWT | Read current risk settings from the shared config store. | Admin |
| `POST` | `/api/admin/settings` | JWT | Update risk settings in the shared config store (Redis + DB). | Admin |
| `GET` | `/api/admin/settings-data` | JWT | Read current risk settings from the shared config store. | Admin |
| `POST` | `/api/admin/settings-data` | JWT | Update risk settings in the shared config store (Redis + DB). | Admin |
| `GET` | `/api/admin/settings-page` | JWT | Settings HTML page. Requires: role >= 'admin'. | Admin |
| `GET` | `/api/admin/settings/performance` | JWT | Live system performance metrics | Settings Extended, Settings Extended |
| `GET` | `/api/admin/settings/system` | JWT | Get system-level admin settings | Admin |
| `POST` | `/api/admin/settings/system` | JWT | Update system-level admin settings | Admin |
| `POST` | `/api/admin/settings/test-smtp` | JWT | Send a test email to verify SMTP configuration | Admin |
| `GET` | `/api/admin/status` | JWT | Active admin alerts (alias for /alerts used by frontend adminApi) | Admin |
| `GET` | `/api/admin/strategies` | JWT | Strategy management page. Requires: role >= 'admin'. | Admin |
| `GET` | `/api/admin/system-info` | JWT | Server version and uptime | Admin |
| `GET` | `/api/admin/system-metrics` | JWT | System resource metrics | Admin |
| `GET` | `/api/admin/users` | JWT | List all platform users | Admin |
| `GET` | `/api/admin/users/{user_id}` | JWT | Get a specific user | Admin |
| `PATCH` | `/api/admin/users/{user_id}` | JWT | Update a user's role or status | Admin |
| `POST` | `/api/admin/users/{user_id}/ban` | JWT | Ban a user | Admin |
| `POST` | `/api/admin/users/{user_id}/impersonate` | JWT | Generate a short-lived JWT impersonation token for support purposes. | Platform, Platform |
| `POST` | `/api/admin/users/{user_id}/reset-password` | JWT | Trigger password reset email | Admin |
| `GET` | `/api/admin/users/{user_id}/trades` | JWT | View a user's trade history from the database. Admin only. | Platform, Platform |
| `POST` | `/api/admin/users/{user_id}/unban` | JWT | Unban a user | Admin |
| `GET` | `/api/advanced/ab-tests` | JWT |  | Advanced Trading |
| `POST` | `/api/advanced/ab-tests/run` | JWT | Start an A/B test between two strategies using the real backtesting engine. | Advanced Trading |
| `GET` | `/api/advanced/ab-tests/{test_id}` | JWT |  | Advanced Trading |
| `GET` | `/api/advanced/correlation` | JWT | Return a rolling Pearson correlation matrix for the default symbol set. | Advanced Trading |
| `GET` | `/api/advanced/cot-sentiment` | JWT | Return CFTC Commitment of Traders data for gold (COMEX). | Advanced Trading |
| `GET` | `/api/ai-core/budget` | JWT | Spend against the ceilings. Scope depends on the caller's role. | AI Core |
| `GET` | `/api/ai-core/cache` | JWT | The response cache, or an honest zero when no deployment installed one. | AI Core |
| `GET` | `/api/ai-core/calls` | JWT | Recent model calls, newest first. Prompts are digests, never text. | AI Core |
| `GET` | `/api/ai-core/capabilities` | JWT | What this caller may do, as the server would decide it. | AI Core |
| `GET` | `/api/ai-core/capabilities/app` | JWT | What the PLATFORM can do, derived from the running route table. | AI Core |
| `GET` | `/api/ai-core/capabilities/registry` | JWT | What the AI Hub specification asks for, and how much of it is real. | AI Core |
| `GET` | `/api/ai-core/chain` | JWT | The resolved chain per role, and which legs this deployment can reach. | AI Core |
| `GET` | `/api/ai-core/departments` | JWT | The Cluster A department directory, and what is actually wired. | AI Core |
| `GET` | `/api/ai-core/evals` | JWT | The latest eval report and what the promotion gate would do with it. | AI Core |
| `GET` | `/api/ai-core/models` | JWT | Which models each vendor currently serves. | AI Core |
| `GET` | `/api/ai-core/review-status` | JWT | What the operator has looked at, and what is worth surfacing. | AI Core |
| `GET` | `/api/ai-core/self/calibration` | JWT | How the stated confidences have actually held up (§5). | AI Core |
| `GET` | `/api/ai-core/self/context` | JWT | What is running for the caller, and what recently finished (§5). | AI Core |
| `GET` | `/api/ai-core/self/depths` | JWT | The explanation registers, and the rule they all obey (§5). | AI Core |
| `GET` | `/api/ai-core/summary` | JWT | One request for the page header, so it does not need seven round trips. | AI Core |
| `GET` | `/api/ai-core/telemetry` | JWT | §22. What the platform can actually measure about itself, and what it cannot. | AI Core |
| `GET` | `/api/ai-memory` | JWT | Everything remembered about the caller, by tier. | AI Memory |
| `POST` | `/api/ai-memory/forget` | JWT | Delete everything remembered about the caller. | AI Memory |
| `GET` | `/api/ai-memory/long-term/pending` | JWT | Facts proposed for permanent retention, awaiting the caller's decision. | AI Memory |
| `POST` | `/api/ai-memory/long-term/{proposal_id}/approve` | JWT | Keep a fact permanently. Nothing reaches long-term without this. | AI Memory |
| `POST` | `/api/ai-memory/long-term/{proposal_id}/reject` | JWT |  | AI Memory |
| `GET` | `/api/ai-memory/tiers` | JWT | What each tier is for and how long it lasts. | AI Memory |
| `PATCH` | `/api/ai-memory/{entry_id}` | JWT | Correct a remembered value, keeping that it was corrected. | AI Memory |
| `GET` | `/api/ai-notifications` | JWT | What the policy delivered, what it is holding, and what is unacknowledged. | AI Notifications |
| `GET` | `/api/ai-notifications/policy` | JWT | This operator's settings, and the floor that no setting can turn off. | AI Notifications |
| `PUT` | `/api/ai-notifications/policy` | JWT | Set quiet hours, sleep mode and rate limits for the calling operator. | AI Notifications |
| `POST` | `/api/ai-notifications/release` | JWT | Deliver anything whose hold has expired. | AI Notifications |
| `POST` | `/api/ai-notifications/reviewed/{surface_id}` | JWT | Record that this operator looked at `surface_id`. | AI Notifications |
| `GET` | `/api/ai-notifications/watches` | JWT | This operator's watches. There is no listing that spans operators. | AI Notifications |
| `POST` | `/api/ai-notifications/watches` | JWT | Add a threshold watch, owned by the caller. | AI Notifications |
| `POST` | `/api/ai-notifications/{key}/acknowledge` | JWT | Stop a notification escalating. Acknowledging is a statement that it was seen. | AI Notifications |
| `GET` | `/api/alerts/` | JWT | List all alerts, optionally filtered by symbol or status. Requires: authenticated user. | Alerts |
| `POST` | `/api/alerts/` | JWT | Create a price alert. Requires: authenticated user. | Alerts |
| `GET` | `/api/alerts/active` | JWT | Return only active (non-paused, non-expired) alerts. Requires: authenticated user. | Alerts |
| `GET` | `/api/alerts/history/triggers` | JWT | Return the last N alert trigger events. Requires: authenticated user. | Alerts |
| `GET` | `/api/alerts/{alert_id}` | JWT | Get a single alert by ID. Requires: authenticated user. | Alerts |
| `DELETE` | `/api/alerts/{alert_id}` | JWT | Delete an alert. Requires: authenticated user. | Alerts |
| `POST` | `/api/alerts/{alert_id}/pause` | JWT | Pause an alert. Requires: authenticated user. | Alerts |
| `POST` | `/api/alerts/{alert_id}/resume` | JWT | Resume a paused alert. Requires: authenticated user. | Alerts |
| `GET` | `/api/analysis/correlation` | JWT | Rolling Pearson correlation matrix for the default symbol set. | Analysis |
| `GET` | `/api/analysis/cot` | JWT | CFTC Commitment of Traders data for gold (COMEX, code 088691). | Analysis |
| `POST` | `/api/auth/2fa/confirm` | JWT | Confirm 2FA setup with a valid TOTP code to activate it. | Authentication |
| `POST` | `/api/auth/2fa/disable` | JWT | Disable 2FA. Requires a valid TOTP code to confirm. | Authentication |
| `POST` | `/api/auth/2fa/setup` | JWT | Generate TOTP secret and QR code URI. Call /2fa/confirm to activate. | Authentication |
| `DELETE` | `/api/auth/account` | JWT | Delete authenticated user account | Settings |
| `POST` | `/api/auth/activate-free-tier` | None | Assign the FREE subscription tier immediately after registration. | Authentication |
| `POST` | `/api/auth/change-password` | JWT | Change authenticated user password | Settings |
| `GET` | `/api/auth/csrf-token` | None | Issue a CSRF token. | Authentication |
| `POST` | `/api/auth/forgot-password` | None | Request a password reset link. | Authentication |
| `POST` | `/api/auth/login` | None | Authenticate and receive access + refresh tokens. | Authentication |
| `POST` | `/api/auth/logout` | JWT | Revoke the current session and blacklist the access token. | Authentication |
| `POST` | `/api/auth/logout-all` | JWT | Revoke all active sessions for the current user. | Authentication |
| `GET` | `/api/auth/me` | JWT | Return current user profile. | Authentication |
| `POST` | `/api/auth/refresh` | None | Rotate refresh token. Returns new access + refresh token pair. | Authentication |
| `POST` | `/api/auth/register` | None | Create a new user account and send a signed email verification link. | Authentication |
| `POST` | `/api/auth/resend-verification` | None | Re-send the email-verification link. | Authentication |
| `POST` | `/api/auth/reset-password` | None | Set a new password using a signed reset token. | Authentication |
| `GET` | `/api/auth/sessions` | JWT | Return all active (non-revoked, non-expired) sessions for the current user. | Authentication |
| `DELETE` | `/api/auth/sessions` | JWT | Revoke all sessions for the current user (alias for logout-all). | Authentication |
| `DELETE` | `/api/auth/sessions/{session_id}` | JWT | Revoke a specific session by ID. Only the owning user can revoke their own sessions. | Authentication |
| `GET` | `/api/auth/verify-email` | None | Verify email address from a signed link token. | Authentication |
| `GET` | `/api/backtesting/list` | JWT | Alias for GET /results — used by the frontend backtesting list view. | Backtesting |
| `POST` | `/api/backtesting/multi-symbol` | JWT | Run multi-symbol backtest | Backtesting |
| `GET` | `/api/backtesting/multi-symbol/latest` | JWT | Latest multi-symbol backtest report | Backtesting |
| `GET` | `/api/backtesting/reconciled/investigation` | JWT | Reconciled backtest root cause investigation results | Backtesting |
| `POST` | `/api/backtesting/reconciled/investigation/refresh` | JWT | Re-run reconciled backtest root cause investigation | Backtesting |
| `GET` | `/api/backtesting/replay/regimes` | None | List available stress regimes | Backtesting |
| `POST` | `/api/backtesting/replay/run` | JWT | Run tick-level backtest via Dukascopy replay | Backtesting |
| `POST` | `/api/backtesting/replay/stress` | JWT | Regime-shift stress test across historical regimes | Backtesting |
| `GET` | `/api/backtesting/results` | JWT | Return the caller's most recent backtest results, newest first. | Backtesting |
| `GET` | `/api/backtesting/results/{run_id}` | JWT | Get one of the caller's backtest results by run_id. | Backtesting |
| `POST` | `/api/backtesting/run` | JWT | Run a backtest for the given strategy and symbol. | Backtesting |
| `GET` | `/api/backtesting/shared/{slug}` | None | Public endpoint — no auth required (intentionally unauthenticated). | Advanced Trading (public) |
| `GET` | `/api/backtesting/strategies` | JWT | List available strategies for backtesting. | Backtesting |
| `GET` | `/api/backtesting/walk-forward` | JWT | List all walk-forward results | Backtesting |
| `GET` | `/api/backtesting/walk-forward/latest` | JWT | Return the most recent walk-forward result. | Backtesting |
| `POST` | `/api/backtesting/walk-forward/run` | JWT | Trigger a walk-forward backtest. Returns run_id immediately; poll GET /walk-forward/{run_id}. | Backtesting |
| `GET` | `/api/backtesting/walk-forward/{run_id}` | JWT | Return one of the caller's walk-forward results. | Backtesting |
| `GET` | `/api/backtesting/{run_id}/monte-carlo` | JWT | Return cached Monte Carlo results. Returns 404 when not yet computed. | Advanced Trading |
| `POST` | `/api/backtesting/{run_id}/monte-carlo` | JWT | Run Monte Carlo simulation on a completed backtest result. | Advanced Trading |
| `GET` | `/api/backtesting/{run_id}/report.pdf` | JWT | Download backtest report as PDF | Backtesting |
| `POST` | `/api/backtesting/{run_id}/share` | JWT | Generate a public share URL for a completed backtest result. | Advanced Trading |
| `POST` | `/api/billing/affiliate/generate-link` | JWT | Get or create the authenticated user's unique referral link. | Billing |
| `POST` | `/api/billing/auth/activate-free-tier` | JWT | Called immediately after successful registration. | Billing |
| `GET` | `/api/billing/balance` | JWT | Return the authenticated user's wallet balance. | Billing |
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
| `GET` | `/api/billing/payment-methods` | JWT | Return the authenticated user's saved Stripe payment methods. | Billing |
| `POST` | `/api/billing/payment-methods` | JWT | Attach a Stripe payment method to the authenticated user's customer record | Billing |
| `DELETE` | `/api/billing/payment-methods/{payment_method_id}` | JWT | Detach (remove) a saved payment method from the authenticated user's | Billing |
| `POST` | `/api/billing/payment-methods/{payment_method_id}/default` | JWT | Set default payment method | Billing |
| `POST` | `/api/billing/payments/flutterwave/init` | JWT | Initialise a Flutterwave payment session. | Billing |
| `GET` | `/api/billing/payments/flutterwave/status` | None | Return whether Flutterwave is configured. | Billing |
| `POST` | `/api/billing/payments/flutterwave/verify` | JWT | Verify a Flutterwave transaction and activate the subscription. | Billing |
| `GET` | `/api/billing/plans` | None | List available subscription plans | Billing |
| `GET` | `/api/billing/stripe/config` | None | Return safe Stripe configuration for the frontend (no secret keys). | Billing |
| `POST` | `/api/billing/stripe/payment-intent` | JWT | Create a Stripe PaymentIntent for the authenticated user. | Billing |
| `GET` | `/api/billing/subscription` | JWT | Return the authenticated user's active subscription. | Billing |
| `POST` | `/api/billing/subscription/cancel` | JWT | Cancel active subscription | Billing |
| `POST` | `/api/billing/subscription/change` | JWT | Change subscription plan | Billing |
| `POST` | `/api/billing/subscription/resume` | JWT | Resume cancelled subscription | Billing |
| `GET` | `/api/billing/transactions` | JWT | Return the authenticated user's transaction history. | Billing |
| `POST` | `/api/billing/webhook/stripe` | None | Stripe webhook receiver — production client with signature verification. | Billing |
| `POST` | `/api/brain/analyze` | JWT | Run AI analysis on a symbol/timeframe | AI Brain |
| `POST` | `/api/brain/chat` | JWT | Free-form chat with the HOPEFX AI trading assistant. | AI Brain |
| `POST` | `/api/brain/complete` | JWT | Raw LLM completion | AI Brain |
| `POST` | `/api/brain/deploy-strategy` | JWT | Deploy a generated strategy to paper/live trading. | AI Brain |
| `POST` | `/api/brain/embed` | JWT | Generate text embeddings | AI Brain |
| `POST` | `/api/brain/generate-strategy` | JWT | Generate a trading strategy from a plain-English prompt. | AI Brain |
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
| `POST` | `/api/broker/test-connection` | JWT | Test broker credentials and return connection status, latency, and balance. | Broker |
| `GET` | `/api/calendar/auto-pause` | JWT | Return the current auto-pause config. | Economic Calendar |
| `POST` | `/api/calendar/auto-pause` | JWT | Configure auto-pause trading before high-impact events. | Economic Calendar |
| `GET` | `/api/calendar/fomc` | JWT | Return FOMC meeting dates with countdown timers. | Economic Calendar |
| `GET` | `/api/calendar/fomc/regime` | JWT | Return the current FOMC regime override status. | Economic Calendar |
| `POST` | `/api/calendar/fomc/regime` | JWT | Record the FOMC outcome and apply a 48-hour regime adjustment. | Economic Calendar |
| `DELETE` | `/api/calendar/fomc/regime` | JWT | Manually clear the FOMC regime override. | Economic Calendar |
| `GET` | `/api/calendar/high-impact` | JWT | Return HIGH and CRITICAL events in the next 48 hours. | Economic Calendar |
| `GET` | `/api/calendar/today` | JWT | Return today's economic events. | Economic Calendar |
| `GET` | `/api/calendar/upcoming` | JWT | Return upcoming economic events within the specified window. | Economic Calendar |
| `GET` | `/api/chaos/mutation/results` | JWT | Return the last mutation test report, or null if none has run. | Chaos & Mutation Testing |
| `POST` | `/api/chaos/mutation/run` | JWT | Trigger mutation testing in the background. | Chaos & Mutation Testing |
| `GET` | `/api/chaos/results` | JWT | Return results from the last chaos run. | Chaos & Mutation Testing |
| `POST` | `/api/chaos/run` | JWT | Run all chaos scenarios against the live data pipeline (paper mode only). | Chaos & Mutation Testing |
| `POST` | `/api/chaos/scenario/{scenario_name}` | JWT | Run a single named chaos scenario. | Chaos & Mutation Testing |
| `GET` | `/api/chaos/status` | JWT | Combined chaos + mutation testing status. | Chaos & Mutation Testing |
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
| `POST` | `/api/chat/rooms/{room_id}/messages/{msg_id}/reactions` | JWT | Add an emoji reaction to a message. Idempotent — adding the same emoji twice is a no-op. | Community Chat |
| `DELETE` | `/api/chat/rooms/{room_id}/messages/{msg_id}/reactions/{emoji}` | JWT | Remove the current user's emoji reaction from a message. | Community Chat |
| `POST` | `/api/chat/rooms/{room_id}/read` | JWT | Mark all messages in a room as read for the current user. | Community Chat |
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
| `POST` | `/api/copy-trading/copies/{copy_id}/pause` | JWT | Pause an active copy trading subscription. | Copy Trading |
| `GET` | `/api/copy-trading/copies/{copy_id}/performance` | JWT | Get performance metrics for a specific copy subscription (must belong to the requesting user). | Copy Trading |
| `POST` | `/api/copy-trading/copies/{copy_id}/resume` | JWT | Resume a paused copy trading subscription. | Copy Trading |
| `PATCH` | `/api/copy-trading/copies/{copy_id}/risk` | JWT | Adjust risk settings for a copy trading subscription. | Copy Trading |
| `POST` | `/api/copy-trading/copies/{copy_id}/stop` | JWT | Stop and remove a copy trading subscription permanently. | Copy Trading |
| `GET` | `/api/copy-trading/masters` | None | Get list of available master traders to copy. | Copy Trading |
| `GET` | `/api/copy-trading/my-copies` | JWT | Retrieve all active copy trading subscriptions for the current user. | Copy Trading |
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
| `GET` | `/api/dashboard/{symbol}/bias` | None | Get market bias summary. | Order Flow Dashboard |
| `GET` | `/api/dashboard/{symbol}/complete` | None | Get complete order flow analysis for a symbol. | Order Flow Dashboard |
| `GET` | `/api/dashboard/{symbol}/levels` | None | Get key S/R levels. | Order Flow Dashboard |
| `GET` | `/api/data-layer/feed-status` | JWT | Whether the price feed can be believed right now, and what is held. | Data Layer |
| `GET` | `/api/data-layer/feeds` | JWT | Per-feed health and configuration status — via orchestrator. | Data Layer |
| `GET` | `/api/data-layer/health` | JWT | Full orchestrator health snapshot. | Data Layer |
| `GET` | `/api/data-layer/lineage` | JWT | Recent lineage records (immutable audit trail) — via orchestrator. | Data Layer |
| `GET` | `/api/data-layer/macro` | JWT | Current macro features and economic calendar — via orchestrator. | Data Layer |
| `GET` | `/api/data-layer/microstructure` | JWT | Current microstructure snapshot — via orchestrator. | Data Layer |
| `GET` | `/api/data-layer/ml-features` | JWT | Complete ML feature set from all data layer components — via orchestrator. | Data Layer |
| `GET` | `/api/data-layer/quality` | JWT | Data quality report — via orchestrator. | Data Layer |
| `GET` | `/api/data-layer/sentiment` | JWT | Current news sentiment signal for gold — via orchestrator. | Data Layer |
| `GET` | `/api/data-layer/tick` | JWT | Latest validated consensus tick. | Data Layer |
| `GET` | `/api/dom/` | None | Get all tracked symbols. | Depth of Market |
| `GET` | `/api/dom/stats` | None | Get service statistics. | Depth of Market |
| `GET` | `/api/dom/{symbol}` | None | Get order book for a symbol. | Depth of Market |
| `GET` | `/api/dom/{symbol}/analysis` | None | Get order book analysis. | Depth of Market |
| `GET` | `/api/dom/{symbol}/history` | None | Get order book history. | Depth of Market |
| `GET` | `/api/dom/{symbol}/imbalance` | None | Get current imbalance. | Depth of Market |
| `GET` | `/api/dom/{symbol}/visualization` | None | Get DOM visualization data. | Depth of Market |
| `GET` | `/api/explain/latest` | JWT | Explain the latest signal | Explainability |
| `GET` | `/api/explain/signal/{signal_id}` | JWT | Explain a specific signal | Explainability |
| `GET` | `/api/explain/{signal_id}` | JWT | Explain a signal by ID or symbol (short-form alias) | Explainability |
| `POST` | `/api/explain/{signal_id}` | JWT | Explain a signal by ID or symbol (POST alias) | Explainability |
| `POST` | `/api/explainability/counterfactual` | JWT | Generate a counterfactual explanation (what would need to change). | Explainability |
| `POST` | `/api/explainability/explain` | JWT | Generate a full explanation for a model prediction. | Explainability |
| `GET` | `/api/explainability/explanation/{explanation_id}/chart` | JWT | Get feature-importance chart data for visualisation. | Explainability |
| `GET` | `/api/explainability/history` | JWT | Get recent explanation history. | Explainability |
| `GET` | `/api/explainability/model/{model_name}/performance` | JWT | Get performance explanation for a named model. | Explainability |
| `GET` | `/api/feed` | None | Return paginated community signal feed (public — no auth required). | Social Feed |
| `POST` | `/api/feed/opt-in` | JWT | Opt the current user into having their signals appear in the public feed. | Social Feed |
| `POST` | `/api/feed/opt-out` | JWT | Opt the current user out of the public feed. | Social Feed |
| `GET` | `/api/feed/status` | JWT | Return the current user's feed opt-in state plus signal and follower counts. | Social Feed |
| `GET` | `/api/feed/status/me` | JWT | Return whether the current user is opted into the public feed. | Social Feed |
| `POST` | `/api/feed/{signal_id}/comment` | JWT | Add a comment to a feed signal. | Social Feed |
| `GET` | `/api/feed/{signal_id}/comments` | None | Return all comments for a signal (public). | Social Feed |
| `POST` | `/api/feed/{signal_id}/react` | JWT | Toggle a thumbs-up or thumbs-down reaction on a signal. | Social Feed |
| `GET` | `/api/health/components` | None | Full structured component health report | Observability |
| `GET` | `/api/health/deep` | None | Deep health check — real I/O probes against every dependency | Observability |
| `GET` | `/api/health/live` | None | Liveness probe — always 200 if process is alive | Observability |
| `GET` | `/api/health/metrics` | None | Prometheus-compatible text/plain metrics snapshot | Observability |
| `GET` | `/api/health/ready` | None | Readiness probe — 503 when any critical component is down | Observability |
| `GET` | `/api/health/startup` | None | Startup probe — 503 until application fully initialised | Observability |
| `GET` | `/api/indicators` | JWT |  | Advanced Trading |
| `POST` | `/api/indicators` | JWT |  | Advanced Trading |
| `POST` | `/api/indicators/preview` | JWT | Evaluate a custom indicator formula against real OHLCV data. | Advanced Trading |
| `PATCH` | `/api/indicators/{ind_id}` | JWT | Update an existing custom indicator (name, formula, parameters). | Advanced Trading |
| `DELETE` | `/api/indicators/{ind_id}` | JWT |  | Advanced Trading |
| `POST` | `/api/indicators/{ind_id}/apply` | JWT | Apply a saved custom indicator to a chart session. | Advanced Trading |
| `GET` | `/api/journal` | JWT | List journal entries (root alias) | Trade Journal |
| `GET` | `/api/journal/emotion-stats` | JWT | Emotion breakdown across journal entries | Trade Journal |
| `GET` | `/api/journal/export` | JWT | Export journal entries as CSV or JSON | Trade Journal |
| `GET` | `/api/journal/mistakes` | JWT | Trades where the user recorded a rule deviation (lessons_learned is set). | Trade Journal |
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
| `GET` | `/api/ml/accuracy` | JWT | Return accuracy metrics for the active model. | ML Models |
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
| `GET` | `/api/ml/models` | JWT | List all available trained models with metadata. Requires authentication. | ML Models |
| `POST` | `/api/ml/predict/{symbol}` | JWT | Generate a trading prediction for the given symbol. | ML Models |
| `POST` | `/api/ml/retrain` | JWT | Trigger background model retraining (admin only) | ML Models |
| `GET` | `/api/ml/rl/status` | JWT | Return RL agent runtime status and saved model inventory. | ML Models, ML Models |
| `POST` | `/api/ml/rl/train` | JWT | Trigger PPO RL agent training on OANDA candles. | ML Models, ML Models |
| `POST` | `/api/ml/rl/walk-forward` | JWT | Run walk-forward evaluation of the PPO agent. | ML Models, ML Models |
| `GET` | `/api/ml/sharpe-circuit-breaker/status` | JWT | Sharpe circuit breaker state for all tracked model versions | ML Models, ML Models |
| `GET` | `/api/ml/signal-filter/stats` | JWT | Signal filter EV statistics — rolling win rate, avg win/loss, EV gate status | ML Models |
| `GET` | `/api/ml/training-jobs` | JWT | List all training jobs (active + recent) | ML Models, ML Models |
| `POST` | `/api/ml/training-jobs` | JWT | Start a model training job | ML Models, ML Models |
| `DELETE` | `/api/ml/training-jobs/{job_id}` | JWT | Cancel a running training job | ML Models, ML Models |
| `GET` | `/api/mlops/drift` | JWT | Return the latest drift detection report. | MLOps |
| `GET` | `/api/mlops/health` | JWT | Return MLOps pipeline health metrics. | MLOps |
| `GET` | `/api/mlops/models/{version_id}/metrics` | JWT | Return metrics for a specific model version (from shadow-deployment results). | MLOps |
| `POST` | `/api/mlops/promote/{version_id}` | JWT | Promote a shadow model to production. | MLOps |
| `POST` | `/api/mlops/retrain` | JWT | Trigger a manual retraining run. | MLOps |
| `GET` | `/api/mlops/retrain/history` | JWT | Return the history of model retrains / promotions for the MLOps dashboard. | MLOps |
| `GET` | `/api/mlops/shadow` | JWT | Return status of all shadow model deployments. | MLOps |
| `GET` | `/api/mobile/config` | JWT | Mobile app configuration | Mobile |
| `GET` | `/api/mobile/notification-prefs` | JWT | Get notification preferences | Mobile |
| `PATCH` | `/api/mobile/notification-prefs` | JWT | Update notification preferences | Mobile |
| `GET` | `/api/mobile/push-status` | JWT | Return FCM status and registered device count for the current user. | Mobile |
| `POST` | `/api/mobile/push-token` | JWT | Register Expo push token (React Native) | Mobile |
| `POST` | `/api/mobile/register-push` | JWT | Register a device FCM token for the authenticated user. | Mobile |
| `DELETE` | `/api/mobile/register-push` | JWT | Remove a device FCM token for the authenticated user. | Mobile |
| `GET` | `/api/mobile/sessions` | JWT | Active mobile sessions | Mobile |
| `DELETE` | `/api/mobile/sessions/{session_id}` | JWT | Revoke a mobile session | Mobile |
| `POST` | `/api/mobile/test-push` | JWT | Send a test push notification to all devices registered for the current user. | Mobile |
| `POST` | `/api/monetization/activate-code` | JWT | Activate an access code for a user. | Monetization |
| `GET` | `/api/monetization/affiliate/leaderboard` | JWT | Get affiliate leaderboard. | Monetization |
| `POST` | `/api/monetization/affiliate/referral` | JWT | Create referral tracking for a referred user. | Monetization |
| `POST` | `/api/monetization/affiliate/signup` | JWT | Sign up for the affiliate program. | Monetization |
| `GET` | `/api/monetization/affiliate/{affiliate_id}/commissions` | JWT | Return commission records for an affiliate. | Monetization |
| `PATCH` | `/api/monetization/affiliate/{affiliate_id}/payment-method` | JWT | Update payment method for affiliate payouts. | Monetization |
| `GET` | `/api/monetization/affiliate/{affiliate_id}/referrals` | JWT | Get all referrals for an affiliate. | Monetization |
| `POST` | `/api/monetization/affiliate/{affiliate_id}/withdraw` | JWT | Request a commission withdrawal for an affiliate. | Monetization |
| `GET` | `/api/monetization/affiliate/{user_id}` | JWT | Get affiliate account for a user, including metrics and monthly breakdown. | Monetization |
| `GET` | `/api/monetization/analytics/dashboard` | JWT | Get revenue analytics dashboard data. Admin only. | Monetization |
| `GET` | `/api/monetization/analytics/growth` | JWT | Get growth metrics (MRR, ARR, churn, LTV, etc). Admin only. | Monetization |
| `GET` | `/api/monetization/analytics/report` | JWT | Generate comprehensive revenue report. Admin only. | Monetization |
| `GET` | `/api/monetization/analytics/revenue` | JWT | Get revenue breakdown by source and tier. Admin only. | Monetization |
| `GET` | `/api/monetization/enterprise/stats` | JWT | Get enterprise program statistics. Admin only. | Monetization |
| `POST` | `/api/monetization/license/validate` | JWT | Validate a subscription license key and report what it entitles. | Monetization |
| `POST` | `/api/monetization/marketplace/creators/stripe-account` | JWT | Link the caller's Stripe Connect account for payouts. | Monetization |
| `GET` | `/api/monetization/marketplace/creators/{creator_id}/balance` | JWT | Get a creator's pending payout balance and earnings summary. | Monetization |
| `GET` | `/api/monetization/marketplace/creators/{creator_id}/payouts` | JWT | List all payout records for a creator. | Monetization |
| `GET` | `/api/monetization/marketplace/creators/{creator_id}/transactions` | JWT | List all sale transactions for a creator. | Monetization |
| `GET` | `/api/monetization/marketplace/featured` | JWT | Get featured strategies. | Monetization |
| `POST` | `/api/monetization/marketplace/list` | JWT | List a new strategy in the marketplace. | Monetization |
| `POST` | `/api/monetization/marketplace/payouts/process` | JWT | Trigger weekly payout processing for all eligible creators (admin only). | Monetization |
| `GET` | `/api/monetization/marketplace/platform/revenue` | JWT | Get aggregate platform revenue metrics (admin only). | Monetization |
| `POST` | `/api/monetization/marketplace/purchase` | JWT | Initiate a strategy purchase via Stripe PaymentIntent. | Monetization |
| `POST` | `/api/monetization/marketplace/review` | JWT | Add a review for a purchased strategy. | Monetization |
| `POST` | `/api/monetization/marketplace/sales` | JWT | Record a marketplace sale and compute the revenue split (admin only). | Monetization |
| `GET` | `/api/monetization/marketplace/stats` | JWT | Get marketplace statistics. | Monetization |
| `GET` | `/api/monetization/marketplace/strategies` | JWT | Search strategies in the marketplace. | Monetization |
| `GET` | `/api/monetization/marketplace/strategies/{strategy_id}` | JWT | Get strategy details. | Monetization |
| `GET` | `/api/monetization/marketplace/strategies/{strategy_id}/reviews` | JWT | Get reviews for a specific strategy. | Monetization |
| `POST` | `/api/monetization/marketplace/strategies/{strategy_id}/reviews` | JWT | Add a review for a strategy — alias matching frontend URL pattern. | Monetization |
| `GET` | `/api/monetization/marketplace/submissions/creator/{creator_id}` | JWT | List all submissions by a creator. | Monetization |
| `GET` | `/api/monetization/marketplace/submissions/pending` | JWT | List all submissions awaiting manual review (admin only). | Monetization |
| `GET` | `/api/monetization/marketplace/submissions/{submission_id}` | JWT | Get a strategy submission and its audit report. | Monetization |
| `POST` | `/api/monetization/marketplace/submissions/{submission_id}/approve` | JWT | Manually approve a strategy submission (admin only). | Monetization |
| `POST` | `/api/monetization/marketplace/submissions/{submission_id}/reject` | JWT | Manually reject a strategy submission (admin only). | Monetization |
| `POST` | `/api/monetization/marketplace/submit` | JWT | Submit a strategy for marketplace listing. | Monetization |
| `GET` | `/api/monetization/marketplace/subscriptions` | JWT | User's marketplace subscriptions | Monetization |
| `DELETE` | `/api/monetization/marketplace/subscriptions/{strategy_id}` | JWT | Cancel a marketplace strategy subscription | Monetization |
| `POST` | `/api/monetization/partner/signup` | JWT | Register a new partner. Admin only. | Monetization |
| `GET` | `/api/monetization/partner/{partner_id}` | JWT | Get partner details. Admin only. | Monetization |
| `GET` | `/api/monetization/pricing` | JWT | Get all pricing tiers. | Monetization |
| `GET` | `/api/monetization/pricing/{tier}` | JWT | Get pricing for a specific tier. | Monetization |
| `POST` | `/api/monetization/subscribe` | JWT | Subscribe to a plan. | Monetization |
| `POST` | `/api/monetization/subscription/{subscription_id}/cancel` | JWT | Cancel a subscription. | Monetization |
| `GET` | `/api/monetization/subscription/{user_id}` | JWT | Get user's current subscription. | Monetization |
| `GET` | `/api/monetization/subscription/{user_id}/limits` | JWT | Get usage limits for a user based on their subscription. | Monetization |
| `GET` | `/api/monetization/validate-code/{code}` | JWT | Validate an access code without activating it. | Monetization |
| `POST` | `/api/monetization/webhook/stripe` | None | Handle Stripe webhooks with signature verification. | Monetization |
| `POST` | `/api/monetization/white-label/create` | JWT | Create a white-label instance for a partner. Admin only. | Monetization |
| `GET` | `/api/news/calendar` | None | Get upcoming economic events that may impact trading. | News Feed |
| `GET` | `/api/news/economic/upcoming` | None | Return upcoming high-impact economic events within the next N hours (1-168). | News & Geopolitical Intelligence |
| `GET` | `/api/news/feed` | None | Retrieve the latest news articles with sentiment scoring. | News Feed |
| `GET` | `/api/news/geopolitical/assessment` | None | Return a full GeopoliticalRiskAssessment including global risk score, | News & Geopolitical Intelligence |
| `GET` | `/api/news/geopolitical/events` | None | Return current geopolitical events tracked by the risk provider. | News & Geopolitical Intelligence |
| `GET` | `/api/news/geopolitical/signal` | None | Return a gold trading signal derived from live geopolitical intelligence. | News & Geopolitical Intelligence |
| `GET` | `/api/news/geopolitical/world-monitor` | None | Return full WorldMonitor dashboard URL suite — gold-relevant regions, crisis hotspots, | News & Geopolitical Intelligence |
| `GET` | `/api/news/latest` | None | Return the most recent news articles for a symbol. | News & Geopolitical Intelligence |
| `GET` | `/api/news/nuclear-score` | None | Get the current nuclear wordmap score for a symbol. | News Feed |
| `GET` | `/api/news/sentiment` | None | Return aggregate market sentiment for a symbol (query-param variant). | News & Geopolitical Intelligence |
| `GET` | `/api/news/sentiment/{symbol}` | None | Return aggregated news sentiment for a trading symbol (e.g. XAUUSD, BTCUSD). | News & Geopolitical Intelligence |
| `GET` | `/api/nocode/blocks` | JWT | Return available building blocks (indicators, conditions, actions). | No-Code Builder |
| `POST` | `/api/nocode/deploy` | JWT | Deploy a no-code strategy template as a live strategy. | No-Code Builder, No-Code Builder |
| `GET` | `/api/nocode/indicators` | JWT | Get list of available indicators for building conditions. | No-Code Builder |
| `GET` | `/api/nocode/node-types` | JWT | Get all available node types for the visual strategy builder. | No-Code Builder, No-Code Builder |
| `GET` | `/api/nocode/strategies` | JWT | List the caller's no-code strategies, plus the built-in templates. | No-Code Builder |
| `POST` | `/api/nocode/strategies` | JWT | Create a new empty no-code strategy. | No-Code Builder |
| `POST` | `/api/nocode/strategies/from-template/{template_id}` | JWT | Create a strategy from a built-in template. | No-Code Builder |
| `POST` | `/api/nocode/strategies/parse` | JWT | Parse a plain-English strategy description into a structured strategy. | No-Code Builder |
| `GET` | `/api/nocode/strategies/{strategy_id}` | JWT | Return a single strategy by ID with all rules. | No-Code Builder |
| `PATCH` | `/api/nocode/strategies/{strategy_id}` | JWT | Update strategy metadata (name, description, symbol, timeframe). | No-Code Builder |
| `DELETE` | `/api/nocode/strategies/{strategy_id}` | JWT | Delete a strategy. | No-Code Builder |
| `POST` | `/api/nocode/strategies/{strategy_id}/backtest` | JWT | Queue a backtest for a no-code strategy. | No-Code Builder |
| `POST` | `/api/nocode/strategies/{strategy_id}/compile` | JWT | Compile a strategy to Python and validate it. | No-Code Builder |
| `GET` | `/api/nocode/strategies/{strategy_id}/export` | JWT | Export one of the caller's no-code strategies as Python code. | No-Code Builder |
| `GET` | `/api/nocode/templates` | JWT | Get list of built-in strategy templates. | No-Code Builder |
| `POST` | `/api/nocode/validate` | JWT | Validate a no-code strategy definition (nodes + edges). | No-Code Builder, No-Code Builder |
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
| `GET` | `/api/observability/alerts` | JWT | Retrieve active observability alerts (latency spikes, error bursts, etc.). | Observability |
| `GET` | `/api/observability/latency-histogram` | JWT | Get latency distribution histogram for request processing. | Observability |
| `GET` | `/api/observability/metrics` | JWT | Retrieve system metrics for the specified period. | Observability |
| `GET` | `/api/observability/services` | JWT | Retrieve the list of all registered services and their health status. | Observability |
| `GET` | `/api/observability/traces` | JWT | Retrieve recent distributed traces across all services. | Observability |
| `GET` | `/api/online-learner/diagnostics` | JWT | Deep diagnostics for both online learner layers | Online Learner |
| `POST` | `/api/online-learner/partial-fit` | JWT | Trigger incremental SGD update for a symbol | Online Learner |
| `POST` | `/api/online-learner/reset` | JWT | Reset the Phase-3 OnlineLearnerStore for a symbol | Online Learner |
| `GET` | `/api/online-learner/status` | JWT | Online learner status for all registered symbols | Online Learner |
| `GET` | `/api/orderflow/stats` | None | Get analyzer statistics. | Order Flow |
| `GET` | `/api/orderflow/{symbol}/analysis` | None | Get order flow analysis. | Order Flow |
| `GET` | `/api/orderflow/{symbol}/delta` | None | Get cumulative delta. | Order Flow |
| `GET` | `/api/orderflow/{symbol}/footprint` | None | Get footprint chart data. | Order Flow |
| `GET` | `/api/orderflow/{symbol}/levels` | None | Get key support/resistance levels. | Order Flow |
| `GET` | `/api/orderflow/{symbol}/profile` | None | Get volume profile for a symbol. | Order Flow |
| `GET` | `/api/orders/advanced/active` | JWT | List the caller's active advanced orders, optionally filtered by position. | Advanced Orders |
| `GET` | `/api/orders/advanced/health` | JWT | Return Advanced Order Manager health metrics. | Advanced Orders |
| `POST` | `/api/orders/advanced/oco` | JWT | Submit an OCO (One-Cancels-the-Other) order. | Advanced Orders |
| `POST` | `/api/orders/advanced/stop-limit` | JWT | Submit a stop-limit order. | Advanced Orders |
| `POST` | `/api/orders/advanced/trailing-stop` | JWT | Submit a trailing stop order. | Advanced Orders |
| `GET` | `/api/orders/advanced/{order_id}` | JWT | Get details of one of the caller's advanced orders. | Advanced Orders |
| `DELETE` | `/api/orders/advanced/{order_id}` | JWT | Cancel an active advanced order. | Advanced Orders |
| `POST` | `/api/payments/crypto/address` | JWT | Generate a unique deposit address for the requested currency. | Payments |
| `GET` | `/api/payments/crypto/rates` | JWT | Return live USD rates for supported cryptocurrencies. | Payments |
| `GET` | `/api/payments/crypto/status/{payment_id}` | JWT | Poll confirmation status for a pending crypto payment. | Payments |
| `POST` | `/api/payments/deposit` | JWT | Initiate a fiat deposit | Payments |
| `POST` | `/api/payments/webhook` | None | Receive on-chain confirmation callbacks from a crypto payment processor | Payments, Payments |
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
| `GET` | `/api/profiles` | None | Return a paginated list of public trader profiles. | Profiles |
| `GET` | `/api/profiles/avatar/{name}` | None | Serve a previously-uploaded avatar image by its stored filename. | Profiles |
| `GET` | `/api/profiles/me` | JWT | Return the authenticated user's profile. | Profiles |
| `PUT` | `/api/profiles/me` | JWT | Update the authenticated user's profile fields. | Profiles |
| `POST` | `/api/profiles/me/avatar` | JWT | Store the uploaded avatar image and return its served URL. | Profiles |
| `GET` | `/api/profiles/{trader_id}` | None | Return a public trader profile. Returns 404 when the trader does not exist. | Profiles |
| `POST` | `/api/profiles/{trader_id}/follow` | JWT | Follow a trader (increments follower count). | Profiles |
| `DELETE` | `/api/profiles/{trader_id}/follow` | JWT | Unfollow a trader. | Profiles |
| `GET` | `/api/profiles/{trader_id}/followers` | None | Return follower count for a trader. | Profiles |
| `GET` | `/api/profiles/{trader_id}/following` | None | Return following count for a trader. | Profiles |
| `GET` | `/api/profiles/{trader_id}/signals` | None | Return recent public signals for a trader. | Profiles |
| `GET` | `/api/profiles/{trader_id}/stats` | None | Return performance stats for a trader. | Profiles |
| `GET` | `/api/profiles/{trader_id}/strategies` | None | Return public strategies for a trader. | Profiles |
| `GET` | `/api/public/prices` | None | Public (no-auth) snapshot of the landing-page ticker prices. | WebSocket Public |
| `GET` | `/api/public/signals` | None | Public (no-auth) teaser of the latest signals for the landing page. | WebSocket Public |
| `GET` | `/api/replay/sessions` | JWT | List all active replay sessions. | Replay |
| `POST` | `/api/replay/sessions` | JWT | Create a new replay session. | Replay |
| `GET` | `/api/replay/sessions/{session_id}` | JWT | Return full session state including bars and trades. | Replay |
| `DELETE` | `/api/replay/sessions/{session_id}` | JWT | Delete a replay session. | Replay |
| `POST` | `/api/replay/sessions/{session_id}/orders` | JWT | Place a practice order in the replay session. | Replay |
| `POST` | `/api/replay/sessions/{session_id}/pause` | JWT | Pause a replay session. | Replay |
| `POST` | `/api/replay/sessions/{session_id}/play` | JWT | Start or resume a replay session. | Replay |
| `POST` | `/api/replay/sessions/{session_id}/resume` | JWT | Resume a paused replay session (or start it if not yet started). | Replay |
| `POST` | `/api/replay/sessions/{session_id}/run` | JWT | Advance the replay session by N bars at once. | Replay |
| `POST` | `/api/replay/sessions/{session_id}/speed` | JWT | Set replay speed (1x, 2x, 5x, 10x, 50x, 100x). | Replay |
| `PUT` | `/api/replay/sessions/{session_id}/speed` | JWT | Set replay speed (1x, 2x, 5x, 10x, 50x, 100x). | Replay |
| `POST` | `/api/replay/sessions/{session_id}/step` | JWT | Advance the replay session by exactly one bar. | Replay |
| `POST` | `/api/replay/sessions/{session_id}/stop` | JWT | Stop and reset a replay session. | Replay |
| `GET` | `/api/replay/sessions/{session_id}/summary` | JWT | Get current session summary (P&L, state, positions). | Replay |
| `GET` | `/api/research/notebooks` | JWT | List all research notebooks (excluding templates). | Research |
| `POST` | `/api/research/notebooks` | JWT | Create a new research notebook. | Research |
| `POST` | `/api/research/notebooks/from-template/{template_id}` | JWT | Create a notebook from a template. | Research |
| `GET` | `/api/research/notebooks/{notebook_id}` | JWT | Return one of the caller's notebooks, including all cells and results. | Research |
| `DELETE` | `/api/research/notebooks/{notebook_id}` | JWT | Delete a notebook. Requires: role >= 'trader'. | Research |
| `POST` | `/api/research/notebooks/{notebook_id}/cells` | JWT | Add a cell to a notebook. | Research |
| `POST` | `/api/research/notebooks/{notebook_id}/cells/{cell_id}/execute` | JWT | Execute a single cell in one of the caller's notebooks. | Research |
| `POST` | `/api/research/notebooks/{notebook_id}/execute` | JWT | Execute all cells in a notebook. Requires: role >= 'trader'. | Research |
| `GET` | `/api/research/notebooks/{notebook_id}/export` | JWT | Export one of the caller's notebooks as JSON or a Python script. | Research |
| `POST` | `/api/research/notebooks/{notebook_id}/run` | JWT | Execute all cells in a notebook (alias for /execute). Requires: role >= 'trader'. | Research |
| `GET` | `/api/research/templates` | JWT | List available notebook templates. | Research |
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
| `GET` | `/api/safe-platform/diagnostics/runs/{run_id}` | JWT | Retrieve a diagnostic run by the id run_diagnostics returned. | Safe Agent Platform |
| `POST` | `/api/safe-platform/evals/run` | JWT | Run the eval suite and file the report the promotion gate reads. | Safe Agent Platform |
| `POST` | `/api/safe-platform/generate` | JWT | Start one generation and return immediately with its job id. | Safe Agent Platform |
| `GET` | `/api/safe-platform/generate/jobs` | JWT | This operator's jobs, for the screen to render all their panels at once. | Safe Agent Platform |
| `POST` | `/api/safe-platform/generate/{job_id}/cancel` | JWT | Stop one of this operator's panels without touching the others. | Safe Agent Platform |
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
| `POST` | `/api/safe-platform/vision/interpret` | JWT | Read one camera frame and return a typed detection. | Safe Agent Platform |
| `GET` | `/api/scanner/criteria` | JWT |  | Market Scanner |
| `POST` | `/api/scanner/criteria` | JWT |  | Market Scanner |
| `DELETE` | `/api/scanner/criteria` | JWT |  | Market Scanner |
| `GET` | `/api/scanner/opportunities` | JWT |  | Market Scanner |
| `GET` | `/api/scanner/opportunities/top` | JWT |  | Market Scanner |
| `GET` | `/api/scanner/results` | JWT | Get last scan results. | Market Scanner |
| `GET` | `/api/scanner/results/{symbol}` | JWT | Get last result for a symbol. | Market Scanner |
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
| `GET` | `/api/security/fixes` | JWT | Return pending fix queue (most recent first). | security-fixes |
| `POST` | `/api/security/fixes/approve` | JWT | Approve an LLM-generated fix and trigger the GitHub PR pipeline. | security-fixes |
| `GET` | `/api/security/fixes/approved` | JWT | Return recently approved fixes with PR metadata. | security-fixes |
| `POST` | `/api/security/fixes/decline` | JWT | Decline an LLM-generated fix. | security-fixes |
| `GET` | `/api/security/fixes/declined` | JWT | Return recently declined fixes. | security-fixes |
| `POST` | `/api/security/fixes/scan` | JWT | Push a vulnerability entry to the scan queue for auto-heal processing. | security-fixes |
| `GET` | `/api/security/fixes/stats` | JWT | Return fix queue statistics. | security-fixes |
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
| `GET` | `/api/sentiment/latest` | None | Get the latest aggregated sentiment overview for a symbol. | Sentiment |
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
| `POST` | `/api/strategies/dynamic/activate` | JWT | Activate a validated strategy version. | Dynamic Strategies |
| `GET` | `/api/strategies/dynamic/active` | JWT | List all currently active dynamic strategies. | Dynamic Strategies |
| `POST` | `/api/strategies/dynamic/deactivate` | JWT | Deactivate an active strategy without retiring it. | Dynamic Strategies |
| `GET` | `/api/strategies/dynamic/health` | JWT | Return Dynamic Strategy Registry health metrics. | Dynamic Strategies |
| `GET` | `/api/strategies/dynamic/list` | JWT | List all registered strategies (active + inactive) for the frontend. | Dynamic Strategies |
| `POST` | `/api/strategies/dynamic/register` | JWT | Register a new dynamic strategy. | Dynamic Strategies |
| `GET` | `/api/strategies/dynamic/versions` | JWT | List all registered strategy versions, optionally filtered by name. | Dynamic Strategies |
| `POST` | `/api/strategies/dynamic/{name}/{action_type}` | JWT | Perform an action on a strategy by name. | Dynamic Strategies |
| `GET` | `/api/stream/stats` | None | Get streaming service statistics. | Streaming |
| `GET` | `/api/stream/{symbol}/bars/{timeframe}` | None | Get aggregated bars for a symbol. | Streaming |
| `GET` | `/api/stream/{symbol}/ticks` | None | Get recent ticks for a symbol. | Streaming |
| `GET` | `/api/superadmin/alerting/channels` | JWT |  |  |
| `GET` | `/api/superadmin/alerting/fired` | JWT |  |  |
| `GET` | `/api/superadmin/alerting/history` | JWT |  |  |
| `GET` | `/api/superadmin/alerting/prometheus` | JWT | Return Prometheus scrape status and alert manager connectivity. |  |
| `GET` | `/api/superadmin/alerting/rules` | JWT |  |  |
| `POST` | `/api/superadmin/alerting/rules` | JWT |  |  |
| `PATCH` | `/api/superadmin/alerting/rules/{rule_id}` | JWT |  |  |
| `DELETE` | `/api/superadmin/alerting/rules/{rule_id}` | JWT |  |  |
| `POST` | `/api/superadmin/alerting/rules/{rule_id}/silence` | JWT |  |  |
| `POST` | `/api/superadmin/alerting/rules/{rule_id}/test` | JWT |  |  |
| `GET` | `/api/superadmin/audit` | JWT |  |  |
| `GET` | `/api/superadmin/audit/export` | JWT |  |  |
| `POST` | `/api/superadmin/auto-healing/approve/{patch_index}` | JWT | Move a pending patch to fixes:approved queue. |  |
| `GET` | `/api/superadmin/auto-healing/audit-log` | JWT | Return the healer audit log (baseline rebuilds, manual actions). |  |
| `POST` | `/api/superadmin/auto-healing/baseline/rebuild` | JWT | Rebuild the SelfHealer integrity baseline from current file state. |  |
| `GET` | `/api/superadmin/auto-healing/config` | JWT | Return the current healing engine configuration. |  |
| `PUT` | `/api/superadmin/auto-healing/config` | JWT | Persist healing config and apply to the live healer. |  |
| `GET` | `/api/superadmin/auto-healing/drift` | JWT | Return recent drift events from the live healer. |  |
| `GET` | `/api/superadmin/auto-healing/patches` | JWT | Return recent patch history from the live healer. |  |
| `GET` | `/api/superadmin/auto-healing/pending-approval` | JWT | Return patches waiting for manual approval. |  |
| `GET` | `/api/superadmin/auto-healing/quarantine` | JWT | Return the quarantine log. |  |
| `GET` | `/api/superadmin/auto-healing/status` | JWT | Live healer status — delegates to SelfHealer singleton. |  |
| `GET` | `/api/superadmin/auto-healing/tests/index` | JWT | Return the cached test discovery index (no re-scan). |  |
| `POST` | `/api/superadmin/auto-healing/tests/reindex` | JWT | Trigger a full codebase test scan using async_reindex (non-blocking). |  |
| `POST` | `/api/superadmin/auto-healing/tests/run` | JWT | Trigger an immediate test run for all enabled categories. |  |
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
| `GET` | `/api/superadmin/diagnostics/checks` | JWT | List all available diagnostic check names with descriptions. |  |
| `POST` | `/api/superadmin/diagnostics/checks/{check_name}/run` | JWT | Run a single named diagnostic check and return its result immediately. |  |
| `POST` | `/api/superadmin/diagnostics/remediate` | JWT | Trigger auto-remediation for all current critical/error findings. |  |
| `GET` | `/api/superadmin/diagnostics/remediation-log` | JWT | Return the auto-remediation action history. |  |
| `GET` | `/api/superadmin/diagnostics/report` | JWT | Return the most recent full diagnostics report. |  |
| `GET` | `/api/superadmin/diagnostics/results` | JWT | Return individual DiagnosticResult entries from the last report, |  |
| `POST` | `/api/superadmin/diagnostics/run` | JWT | Trigger a full diagnostic run (all 10 checks) in the background. |  |
| `GET` | `/api/superadmin/diagnostics/summary` | JWT | Return a concise health summary combining healer status and diagnostics. |  |
| `GET` | `/api/superadmin/engine/config` | JWT |  |  |
| `PATCH` | `/api/superadmin/engine/config` | JWT |  |  |
| `POST` | `/api/superadmin/engine/kill-switch` | JWT |  |  |
| `GET` | `/api/superadmin/engine/metrics` | JWT | Return trading engine KPIs — all fields populated from real DB/engine data. |  |
| `POST` | `/api/superadmin/engine/pause` | JWT |  |  |
| `POST` | `/api/superadmin/engine/resume` | JWT |  |  |
| `GET` | `/api/superadmin/engine/status` | JWT | Rich engine status: config + live app_state engine attributes. |  |
| `GET` | `/api/superadmin/feature-flags` | JWT |  |  |
| `GET` | `/api/superadmin/feature-flags/overrides/{target_user_id}` | JWT |  |  |
| `PATCH` | `/api/superadmin/feature-flags/overrides/{target_user_id}/{flag_name}` | JWT |  |  |
| `PATCH` | `/api/superadmin/feature-flags/{flag_name}` | JWT |  |  |
| `GET` | `/api/superadmin/financial/affiliates` | JWT |  |  |
| `GET` | `/api/superadmin/financial/chargebacks` | JWT | Return chargeback records from the database. |  |
| `PATCH` | `/api/superadmin/financial/chargebacks/{chargeback_id}` | JWT | Update chargeback status (e.g. mark as won/lost after submitting evidence). |  |
| `GET` | `/api/superadmin/financial/fee-config` | JWT | Platform-wide fee configuration. |  |
| `PATCH` | `/api/superadmin/financial/fee-config` | JWT | Update platform fee configuration. |  |
| `GET` | `/api/superadmin/financial/payments` | JWT |  |  |
| `POST` | `/api/superadmin/financial/payments/{payment_id}/refund` | JWT |  |  |
| `GET` | `/api/superadmin/financial/payouts` | JWT | Affiliate and withdrawal payout queue. |  |
| `GET` | `/api/superadmin/financial/reconciliation` | JWT | Return reconciliation records from the database. |  |
| `POST` | `/api/superadmin/financial/reconciliation/run` | JWT | Trigger a reconciliation run for a given period and provider. |  |
| `PATCH` | `/api/superadmin/financial/reconciliation/{recon_id}` | JWT | Mark a reconciliation record as resolved with optional notes. |  |
| `GET` | `/api/superadmin/financial/refund-policy` | JWT | Return the refund policy in force plus every option and what it means. |  |
| `PUT` | `/api/superadmin/financial/refund-policy` | JWT | Set the refund policy. |  |
| `GET` | `/api/superadmin/financial/revenue` | JWT | Return real revenue KPIs from RevenueAnalytics and SubscriptionManager. |  |
| `GET` | `/api/superadmin/financial/subscriptions` | JWT |  |  |
| `GET` | `/api/superadmin/financial/tax-reports` | JWT | Return tax report records from the database. |  |
| `POST` | `/api/superadmin/financial/tax-reports` | JWT | Create or regenerate a tax report for a given period and jurisdiction. |  |
| `PATCH` | `/api/superadmin/financial/tax-reports/{report_id}` | JWT | Update a tax report (e.g. mark as filed or paid). |  |
| `GET` | `/api/superadmin/financial/wallets` | JWT | Platform wallet balances and transaction summaries. |  |
| `GET` | `/api/superadmin/gdpr/consent-log` | JWT |  |  |
| `GET` | `/api/superadmin/gdpr/requests` | JWT |  |  |
| `POST` | `/api/superadmin/gdpr/requests/{req_id}/process` | JWT |  |  |
| `GET` | `/api/superadmin/gdpr/retention-policies` | JWT |  |  |
| `PATCH` | `/api/superadmin/gdpr/retention-policies` | JWT |  |  |
| `POST` | `/api/superadmin/gdpr/users/{user_id}/erase` | JWT |  |  |
| `POST` | `/api/superadmin/gdpr/users/{user_id}/export` | JWT |  |  |
| `GET` | `/api/superadmin/health-engine/history` | JWT | Return the last N health reports stored in Redis. |  |
| `POST` | `/api/superadmin/health-engine/probe/{name}` | JWT | Run a single named probe immediately. |  |
| `GET` | `/api/superadmin/health-engine/probes` | JWT | List all registered probe names. |  |
| `POST` | `/api/superadmin/health-engine/register` | JWT | Register a custom HTTP probe. |  |
| `POST` | `/api/superadmin/health-engine/run` | JWT | Run a subset of probes. Body: {"probes": ["database", "redis", ...]} |  |
| `GET` | `/api/superadmin/health-engine/status` | JWT | Run all registered probes and return a full health report. |  |
| `GET` | `/api/superadmin/infra/cache` | JWT |  |  |
| `POST` | `/api/superadmin/infra/cache/flush` | JWT |  |  |
| `GET` | `/api/superadmin/infra/db` | JWT |  |  |
| `GET` | `/api/superadmin/infra/health` | JWT |  |  |
| `GET` | `/api/superadmin/infra/queues` | JWT |  |  |
| `GET` | `/api/superadmin/logs` | JWT |  |  |
| `GET` | `/api/superadmin/logs/export` | JWT | Export filtered log entries as plain text (one line per entry). |  |
| `GET` | `/api/superadmin/logs/levels` | JWT |  |  |
| `PATCH` | `/api/superadmin/logs/levels` | JWT |  |  |
| `GET` | `/api/superadmin/ml/ab-tests` | JWT | Active A/B tests for ML models. |  |
| `POST` | `/api/superadmin/ml/deploy` | JWT |  |  |
| `GET` | `/api/superadmin/ml/drift` | JWT | Model drift metrics for all deployed models. |  |
| `GET` | `/api/superadmin/ml/explainability` | JWT | SHAP / feature importance for a deployed model. |  |
| `GET` | `/api/superadmin/ml/metrics` | JWT |  |  |
| `GET` | `/api/superadmin/ml/models` | JWT | Return all registered model versions mapped to the MLModel interface. |  |
| `POST` | `/api/superadmin/ml/retrain/{model_name}` | JWT |  |  |
| `POST` | `/api/superadmin/ml/rl/control` | JWT |  |  |
| `GET` | `/api/superadmin/ml/rl/status` | JWT |  |  |
| `POST` | `/api/superadmin/ml/rollback/{model_name}` | JWT |  |  |
| `GET` | `/api/superadmin/ml/status` | JWT | Return ML engine status in the shape the frontend MLStatus interface expects. |  |
| `GET` | `/api/superadmin/ml/training-jobs` | JWT | Active and recent ML training jobs. |  |
| `POST` | `/api/superadmin/nuclear/halt` | JWT |  |  |
| `POST` | `/api/superadmin/nuclear/hedge/activate` | JWT |  |  |
| `POST` | `/api/superadmin/nuclear/hedge/deactivate` | JWT |  |  |
| `GET` | `/api/superadmin/nuclear/log` | JWT |  |  |
| `POST` | `/api/superadmin/nuclear/resume` | JWT |  |  |
| `POST` | `/api/superadmin/nuclear/risk-override` | JWT |  |  |
| `GET` | `/api/superadmin/nuclear/status` | JWT |  |  |
| `GET` | `/api/superadmin/overview` | JWT | Platform-wide health snapshot — all KPI fields populated from real data. |  |
| `POST` | `/api/superadmin/platform/broadcast` | JWT |  |  |
| `GET` | `/api/superadmin/platform/config` | JWT |  |  |
| `PATCH` | `/api/superadmin/platform/config` | JWT |  |  |
| `PUT` | `/api/superadmin/platform/config/full` | JWT | Accept and persist the complete platform config (all 200+ fields). |  |
| `GET` | `/api/superadmin/platform/config/validate` | JWT | Validate the current platform config for consistency and completeness. |  |
| `POST` | `/api/superadmin/platform/maintenance` | JWT |  |  |
| `POST` | `/api/superadmin/platform/test-smtp` | JWT | Test SMTP connectivity using the current platform config or a provided override. |  |
| `GET` | `/api/superadmin/rate-limits` | JWT |  |  |
| `POST` | `/api/superadmin/rate-limits` | JWT |  |  |
| `GET` | `/api/superadmin/rate-limits/rules` | JWT |  |  |
| `POST` | `/api/superadmin/rate-limits/rules` | JWT |  |  |
| `PATCH` | `/api/superadmin/rate-limits/rules/{rule_id}` | JWT |  |  |
| `DELETE` | `/api/superadmin/rate-limits/rules/{rule_id}` | JWT |  |  |
| `GET` | `/api/superadmin/rate-limits/stats` | JWT |  |  |
| `GET` | `/api/superadmin/rate-limits/violations` | JWT | Return recent rate-limit violation events from the audit log. |  |
| `PATCH` | `/api/superadmin/rate-limits/{rule_id}` | JWT |  |  |
| `DELETE` | `/api/superadmin/rate-limits/{rule_id}` | JWT |  |  |
| `POST` | `/api/superadmin/rate-limits/{rule_id}/reset` | JWT |  |  |
| `GET` | `/api/superadmin/reliability/components` | JWT | Per-component health with labels and descriptions. |  |
| `GET` | `/api/superadmin/reliability/env` | JWT | Audit environment variables — shows presence/absence without values. |  |
| `GET` | `/api/superadmin/reliability/history` | JWT | Return the last N reliability snapshots stored in Redis. |  |
| `POST` | `/api/superadmin/reliability/history/record` | JWT | Manually push the current reliability status into the history ring. |  |
| `GET` | `/api/superadmin/reliability/metrics` | JWT | Return reliability metrics for dashboard widgets. |  |
| `POST` | `/api/superadmin/reliability/probe` | JWT | Run a single named connectivity probe and return its result. |  |
| `GET` | `/api/superadmin/reliability/routes` | JWT | Return all registered FastAPI routes with methods and tags. |  |
| `POST` | `/api/superadmin/reliability/self-test` | JWT | Run the full end-to-end self-test suite across all components. |  |
| `GET` | `/api/superadmin/reliability/status` | JWT | Full system reliability snapshot — runs all probes concurrently. |  |
| `POST` | `/api/superadmin/reliability/trace/test` | JWT | Emit a full end-to-end test trace: frontend→API→DB→Redis→broker. |  |
| `GET` | `/api/superadmin/reliability/traces` | JWT | Return recent OTel spans from the in-memory ring buffer. |  |
| `POST` | `/api/superadmin/reliability/validate-toggle` | JWT | Validate that a toggle/setting change was persisted end-to-end. |  |
| `GET` | `/api/superadmin/reliability/validate/{setting_key}` | JWT | Verify a platform config key is persisted in both Redis and DB. |  |
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
| `POST` | `/api/superadmin/risk/circuit-breakers/{name}/open` | JWT | Halt new orders on a breaker and hold it open until a human resets it. |  |
| `POST` | `/api/superadmin/risk/circuit-breakers/{name}/reset` | JWT | Lift the manual hold on a breaker and re-arm its normal recovery path. |  |
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
| `POST` | `/api/superadmin/security-infra/hsm/keys/{key_id}/rotate` | JWT | Rotate an HSM-managed key. |  |
| `GET` | `/api/superadmin/security-infra/log` | JWT | Return recent security infrastructure events. |  |
| `GET` | `/api/superadmin/security-infra/self-healer` | JWT | Return SelfHealer engine status and recent heal events. |  |
| `POST` | `/api/superadmin/security-infra/self-healer/scan` | JWT | Trigger an immediate self-healer integrity scan. |  |
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
| `GET` | `/api/superadmin/system-health/dependencies` | JWT | Return a dependency health graph for visualisation. |  |
| `GET` | `/api/superadmin/system-health/jobs` | JWT |  |  |
| `POST` | `/api/superadmin/system-health/jobs/{job_id}/run` | JWT |  |  |
| `GET` | `/api/superadmin/system-health/resources` | JWT |  |  |
| `GET` | `/api/superadmin/system-health/services` | JWT |  |  |
| `GET` | `/api/superadmin/system/api-keys` | JWT | List platform-level API keys (alias for security-infra endpoint). |  |
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
| `POST` | `/api/superadmin/users/bulk/ban` | JWT | Ban multiple users in a single request. Skips superadmins. |  |
| `POST` | `/api/superadmin/users/bulk/export` | JWT | Export selected users as CSV. Pass empty user_ids to export all. |  |
| `POST` | `/api/superadmin/users/bulk/unban` | JWT | Unban multiple users in a single request. |  |
| `GET` | `/api/superadmin/users/{user_id}` | JWT |  |  |
| `PATCH` | `/api/superadmin/users/{user_id}` | JWT |  |  |
| `DELETE` | `/api/superadmin/users/{user_id}` | JWT |  |  |
| `GET` | `/api/superadmin/users/{user_id}/activity` | JWT |  |  |
| `POST` | `/api/superadmin/users/{user_id}/ban` | JWT |  |  |
| `POST` | `/api/superadmin/users/{user_id}/impersonate` | JWT | Issue a short-lived impersonation token for the target user. |  |
| `PATCH` | `/api/superadmin/users/{user_id}/plan` | JWT | Persist a plan change immediately on the User row. |  |
| `POST` | `/api/superadmin/users/{user_id}/reset-password` | JWT | Generate a temporary password and store it using the canonical hash scheme. |  |
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
| `GET` | `/api/support/queue` | JWT | Tickets waiting on a person |  |
| `GET` | `/api/support/queue/{ticket_id}` | JWT | One queued ticket, with its thread |  |
| `POST` | `/api/support/queue/{ticket_id}/claim` | JWT | Take a ticket |  |
| `POST` | `/api/support/queue/{ticket_id}/release` | JWT | Put a ticket back |  |
| `POST` | `/api/support/queue/{ticket_id}/reply` | JWT | Reply to the customer |  |
| `POST` | `/api/support/queue/{ticket_id}/resolve` | JWT | Close a ticket |  |
| `GET` | `/api/support/tickets` | JWT | My support tickets |  |
| `POST` | `/api/support/tickets` | JWT | Open a support ticket |  |
| `GET` | `/api/support/tickets/{ticket_id}` | JWT | One of my tickets, with its thread |  |
| `POST` | `/api/support/tickets/{ticket_id}/messages` | JWT | Reply on my own ticket |  |
| `GET` | `/api/tca/alerts` | JWT | Return brokers currently above the slippage alert threshold. | tca |
| `GET` | `/api/tca/records` | JWT | Return the N most recent TCA records, optionally filtered. | tca |
| `DELETE` | `/api/tca/records` | JWT | Flush all in-memory TCA records (admin only). | tca |
| `GET` | `/api/tca/report` | JWT | Return per-broker TCA reports for all brokers with recent fills. | tca |
| `GET` | `/api/tca/report/{broker}` | JWT | Return TCA report for a specific broker, optionally filtered by symbol/session. | tca |
| `GET` | `/api/tca/stats` | JWT | Rolling execution quality statistics across all brokers. | tca |
| `GET` | `/api/teams` | JWT | List all teams, optionally filtered by user membership. | Teams |
| `POST` | `/api/teams` | JWT | Create a new team. | Teams |
| `GET` | `/api/teams/` | JWT | List all teams, optionally filtered by user membership. | Teams |
| `POST` | `/api/teams/` | JWT | Create a new team. | Teams |
| `POST` | `/api/teams/invitations/accept` | JWT | Accept a team invitation using the invitation token. | Teams |
| `GET` | `/api/teams/{team_id}` | JWT | Get a team summary. | Teams |
| `DELETE` | `/api/teams/{team_id}` | JWT | Delete a team and all its data. | Teams |
| `GET` | `/api/teams/{team_id}/activity` | JWT | Get team activity log. | Teams |
| `POST` | `/api/teams/{team_id}/invite` | JWT | Invite a user to the team. | Teams |
| `POST` | `/api/teams/{team_id}/members` | JWT | Invite a member to the team (alias for /invite using members path). | Teams |
| `PATCH` | `/api/teams/{team_id}/members/{user_id}` | JWT | Update a member's role (PATCH alias for PUT /{team_id}/members/{user_id}/role). | Teams |
| `DELETE` | `/api/teams/{team_id}/members/{user_id}` | JWT | Remove a member from the team. | Teams |
| `GET` | `/api/teams/{team_id}/members/{user_id}/permissions` | JWT | Get a member's effective permissions. | Teams |
| `PUT` | `/api/teams/{team_id}/members/{user_id}/role` | JWT | Change a member's role. | Teams |
| `GET` | `/api/teams/{team_id}/performance` | JWT | Return aggregated P&L and performance metrics for a team. | Teams |
| `GET` | `/api/timesales/stats` | None | Get service statistics. | Time & Sales |
| `GET` | `/api/timesales/{symbol}/aggressor` | None | Get aggressor statistics. | Time & Sales |
| `GET` | `/api/timesales/{symbol}/histogram` | None | Get price/volume histogram. | Time & Sales |
| `GET` | `/api/timesales/{symbol}/large` | None | Get large trades for a symbol. | Time & Sales |
| `GET` | `/api/timesales/{symbol}/recent` | None | Get recent trades for a symbol. | Time & Sales |
| `GET` | `/api/timesales/{symbol}/statistics` | None | Get trade statistics. | Time & Sales |
| `GET` | `/api/timesales/{symbol}/velocity` | None | Get trade velocity metrics. | Time & Sales |
| `GET` | `/api/tracing/config` | JWT | Get current OpenTelemetry configuration | Observability |
| `GET` | `/api/tracing/spans` | JWT | Return last 100 spans from in-memory ring buffer | Observability |
| `POST` | `/api/tracing/test` | JWT | Emit a test span and return its trace ID | Observability |
| `GET` | `/api/trading/account` | JWT | Get full AccountMetrics snapshot | Trading |
| `POST` | `/api/trading/ai-analysis` | JWT | AI chart-click analysis | Trading |
| `GET` | `/api/trading/balance` | JWT | Account balance (alias for /account) | Trading |
| `GET` | `/api/trading/brain-state` | JWT | Get AI brain state. Returns a graceful fallback when brain is not yet initialised. | Trading |
| `GET` | `/api/trading/depth/{symbol}` | JWT | Get order book depth (bid/ask ladder) for a symbol | Trading |
| `POST` | `/api/trading/emergency-stop` | JWT | Trigger emergency stop — halts all trading immediately. | Trading |
| `GET` | `/api/trading/equity-curve` | JWT | Equity curve data points | Trading |
| `GET` | `/api/trading/history` | JWT | Trade history (alias for /trades) | Trading |
| `GET` | `/api/trading/levels` | JWT | Support and resistance levels for a symbol | Trading |
| `GET` | `/api/trading/microstructure` | JWT | Market microstructure snapshot | Trading |
| `GET` | `/api/trading/ohlcv/{symbol:path}` | JWT | Get OHLCV candlestick data for a symbol | Trading |
| `GET` | `/api/trading/orders` | JWT | List open and recent orders | Trading |
| `POST` | `/api/trading/orders` | JWT | Place a market/limit/stop order | Trading |
| `PATCH` | `/api/trading/orders/{order_id}` | JWT | Modify price, quantity, SL, or TP on a pending order | Trading |
| `DELETE` | `/api/trading/orders/{order_id}` | JWT | Cancel a pending or open order | Trading |
| `POST` | `/api/trading/paper/start` | JWT | Activate paper trading mode for the authenticated user. | Trading |
| `POST` | `/api/trading/paper/stop` | JWT | Deactivate paper trading mode for the authenticated user. | Trading |
| `GET` | `/api/trading/patterns` | JWT | Chart patterns for a symbol | Trading |
| `GET` | `/api/trading/performance/summary` | JWT |  |  |
| `GET` | `/api/trading/performance/{strategy_id}` | JWT |  |  |
| `POST` | `/api/trading/position-size` | JWT |  |  |
| `GET` | `/api/trading/positions` | JWT | Get the authenticated user's open positions — theirs and only theirs. | Trading |
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
| `GET` | `/api/trading/trades` | JWT | Return paginated trade history for the authenticated user. | Trading |
| `GET` | `/api/trading/trades/export` | JWT | Download trade history as a CSV file. | Trading |
| `GET` | `/api/trading/trendlines` | JWT | Trendlines for a symbol | Trading |
| `GET` | `/api/transparency/audit` | JWT | Get execution audit trail, optionally filtered by order ID. | Transparency |
| `GET` | `/api/transparency/audit-log` | JWT | Retrieve the audit log of all system actions (trades, config changes, risk events). | Transparency |
| `GET` | `/api/transparency/best-execution` | JWT | Best-execution report (alias) | Transparency |
| `GET` | `/api/transparency/decisions` | None | Retrieve recent trade decisions with full factor breakdowns. | Transparency |
| `POST` | `/api/transparency/executions` | JWT | Record a trade execution for transparency tracking. | Transparency |
| `GET` | `/api/transparency/explain/{trade_id}` | None | Get detailed explanation for a specific trade decision. | Transparency |
| `GET` | `/api/transparency/latency/trend` | JWT | Get daily latency trend data. | Transparency |
| `GET` | `/api/transparency/orders/{order_id}` | JWT | Get execution details for a specific order. | Transparency |
| `GET` | `/api/transparency/report` | JWT | Generate an execution quality report for the last N days. | Transparency |
| `GET` | `/api/transparency/slippage` | JWT | Slippage distribution (alias) | Transparency |
| `GET` | `/api/transparency/slippage/distribution` | JWT | Get slippage distribution data for charting. | Transparency |
| `GET` | `/api/transparency/statement` | None | One auditable client statement bundling the controls a client/auditor wants: | Transparency |
| `GET` | `/api/transparency/stats` | None | Aggregate statistics about decision quality and model performance. | Transparency |
| `GET` | `/api/transparency/summary` | JWT | Execution transparency summary | Transparency |
| `GET` | `/api/transparency/venues` | JWT | Trading venue performance | Transparency |
| `GET` | `/api/tutorials` | JWT | List the tutorial catalogue with per-episode lock flags | Tutorials |
| `GET` | `/api/tutorials/{episode}` | JWT | Get one episode (video_url gated by plan) | Tutorials |
| `GET` | `/api/voice/status` | JWT | Report which cloud voice providers are configured. The frontend uses this | Voice |
| `POST` | `/api/voice/stt` | JWT | Transcribe an uploaded audio clip to text via OpenAI Whisper. Returns 503 | Voice |
| `POST` | `/api/voice/tts` | JWT | Synthesize ``req.text`` to speech and return the audio bytes. Returns 503 | Voice |
| `GET` | `/api/watchlist` | JWT | Return the authenticated user's watchlist with live prices. | Watchlist |
| `PUT` | `/api/watchlist/order` | JWT | Reorder watchlist symbols (PUT alias for PATCH /order) | Watchlist |
| `PATCH` | `/api/watchlist/order` | JWT | Persist a drag-to-reorder operation. | Watchlist |
| `GET` | `/api/watchlist/prices` | JWT | Return live prices for all symbols in the authenticated user's watchlist. | Watchlist |
| `POST` | `/api/watchlist/{symbol}` | JWT | Add a symbol to the authenticated user's watchlist. | Watchlist |
| `DELETE` | `/api/watchlist/{symbol}` | JWT | Remove a symbol from the authenticated user's watchlist. | Watchlist |
| `POST` | `/api/webhooks/tradingview` | None | Receive TradingView alert and ingest as trading signal | Webhooks |
| `GET` | `/api/whitelabel/features` | JWT | Return all available feature flags. | Whitelabel |
| `GET` | `/api/whitelabel/tenants` | JWT |  | Whitelabel |
| `POST` | `/api/whitelabel/tenants` | JWT |  | Whitelabel |
| `GET` | `/api/whitelabel/tenants/{tenant_id}` | JWT |  | Whitelabel |
| `PATCH` | `/api/whitelabel/tenants/{tenant_id}` | JWT |  | Whitelabel |
| `DELETE` | `/api/whitelabel/tenants/{tenant_id}` | JWT |  | Whitelabel |
| `POST` | `/api/whitelabel/tenants/{tenant_id}/activate` | JWT |  | Whitelabel |
| `POST` | `/api/whitelabel/tenants/{tenant_id}/api-key` | JWT | Generate a new API key. Shown once — stored as SHA-256 hash. | Whitelabel |
| `POST` | `/api/whitelabel/tenants/{tenant_id}/features/{feature}` | JWT |  | Whitelabel |
| `DELETE` | `/api/whitelabel/tenants/{tenant_id}/features/{feature}` | JWT |  | Whitelabel |
| `GET` | `/api/whitelabel/tenants/{tenant_id}/preview` | JWT | Return branded theme data for dashboard preview. | Whitelabel |
| `POST` | `/api/whitelabel/tenants/{tenant_id}/suspend` | JWT |  | Whitelabel |
| `POST` | `/kyc/applicants` | JWT | Create a KYC applicant and return the provider SDK token. | kyc |
| `GET` | `/kyc/applicants/{applicant_id}/status` | JWT | Poll the KYC provider for the current verification status. | kyc |
| `POST` | `/kyc/sanctions/screen` | JWT | Manual sanctions screening. Requires admin role. | kyc |
| `GET` | `/kyc/status` | JWT | Return the current user's KYC status from the compliance manager. | kyc |
| `POST` | `/kyc/webhooks/onfido` | None | Onfido webhook callback. | kyc |
| `POST` | `/kyc/webhooks/sumsub` | None | Sumsub webhook callback. | kyc |
| `GET` | `/mobile/api/v2/account` | JWT | Get account overview | Mobile, Account |
| `POST` | `/mobile/api/v2/auth/login` | None | Login mobile user | Mobile, Auth |
| `POST` | `/mobile/api/v2/auth/refresh` | None | Refresh access token | Mobile, Auth |
| `POST` | `/mobile/api/v2/auth/register` | None | Register new mobile user | Mobile, Auth |
| `GET` | `/mobile/api/v2/news` | JWT | Get latest financial news | Mobile, News |
| `GET` | `/mobile/api/v2/notifications/preferences` | JWT | Get notification preferences | Mobile, Notifications |
| `POST` | `/mobile/api/v2/notifications/preferences` | JWT | Update notification preferences | Mobile, Notifications |
| `POST` | `/mobile/api/v2/orders` | JWT | Place new order | Mobile, Trading |
| `GET` | `/mobile/api/v2/performance` | JWT | Get performance data | Mobile, Analytics |
| `GET` | `/mobile/api/v2/quotes/{symbol}` | JWT | Get real-time quote | Mobile, Trading |
| `GET` | `/mobile/api/v2/trades` | JWT | Get all open trades | Mobile, Trading |
| `POST` | `/mobile/api/v2/trades/{trade_id}/close` | JWT | Close specific trade | Mobile, Trading |
| `GET` | `/mobile/health` | None |  | Mobile, Health |
| `GET` | `/superadmin/ai-operations/permissions` | JWT |  | ai-operations |
| `POST` | `/superadmin/ai-operations/permissions/review` | JWT |  | ai-operations |
| `POST` | `/superadmin/ai-operations/recovery/assess` | JWT |  | ai-operations |
| `GET` | `/superadmin/ai-operations/recovery/latest` | JWT |  | ai-operations |
| `GET` | `/ws/live/stats` | None | Current WebSocket connection stats. | WebSocket Live |
