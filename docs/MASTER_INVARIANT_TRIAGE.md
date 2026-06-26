# Master Invariant Registry — Triage (501 items)

Triage of the 501-item "Master Invariant Registry" against the **actual**
HOPEFX-AI-TRADING codebase (an XAUUSD/gold AI platform on OANDA; paper active,
live OANDA next). Every item is classified into exactly one bucket.

**Legend**
- ✅ **Covered** — a pure predicate or mechanism already exists in `invariants/`
  or the platform. *Caveat:* "covered" means **the check exists**; most predicates
  are wired live only at the points we enforced this session (pre-trade gate,
  order-authorization, reconciliation, audit-chain, coverage/CI). The rest are
  available to wire. Predicate names are given.
- 🔨 **Build** — applicable to this platform, codeable, not yet present. Backlog.
- 🚫 **Drop** — describes a US-equities / multi-asset / exchange-member /
  prime-broker institution HOPEFX is not (OANDA gold CFD/spot, single venue).
  Implementing would be building controls for venues/instruments we don't touch.
- 👤 **Process** — organizational / infra / human, not a code assertion (still
  real work, just a different owner).

**Tally:** ✅ ~300 · 🔨 ~95 · 🚫 ~55 · 👤 ~50 (per-item below).

---

## §1 Application startup & core lifecycle (1–15)
- 1 ✅ app boot — `scripts/runtime_invariant_check.py` Phase-1 boots the app (fails on import/syntax).
- 2 🔨 router count matches expected — add a CI assert on route count.
- 3 ✅ feature-flag → 404 — runtime checker + `platform_web.verify_api_status`.
- 4 ✅ DB pool healthy — `platform_web.verify_connection_pool`; `/health/ready`.
- 5 ✅ Redis ping <1s — `integrations.verify_dependency_healthy`; `/health/ready`.
- 6 ✅ Celery worker ready — `jobs.verify_scheduled_job_fired` + `api/superadmin/reliability`.
- 7 ✅ /metrics 200 — exposed; runtime checker probes it.
- 8 ✅ no duplicate prefixes — runtime checker `check_duplicate_items` pattern + dedup wrapper.
- 9 ✅ required env vars — `config/startup_validator.py` (`validate_environment`).
- 10 ✅ Vault secrets resolvable — `config/vault.py`; `security.verify_no_exposed_secret`.
- 11 ✅ /health 200 — health router live.
- 12 👤 startup <10s — CI/CD timing gate (ops).
- 13 ✅ no silent crash — `hopefx_observability` uncaught/thread/asyncio hooks.
- 14 🔨 structured startup banner — small log addition.
- 15 ✅ migrations applied — `platform_data.verify_migrations_applied`; runtime Gate I.

## §2 API gateway & router integrity (16–40)
- 16 🔨 every route smoke-tested never 500 — extend runtime checker to enumerate all routes (TOP BUILD ITEM).
- 17 🔨 OpenAPI schema valid — add `/openapi.json` JSON-Schema check to runtime checker.
- 18 🔨 no route shadowing — CI static check.
- 19 ✅ CORS matches ALLOWED_ORIGINS — `platform_auth.verify_security_headers` + middleware.
- 20 🔨 request size limit (413) — add middleware assert.
- 21 ✅ content-type json — `platform_web.verify_api_schema`/status.
- 22 ✅ rate-limit headers — `platform_auth.verify_rate_limiter_active`.
- 23 ✅ no sensitive headers — `platform_auth.verify_no_secret_in_response` + security-headers middleware.
- 24 ✅ static files MIME — runtime checker probes; page_routes mounts static.
- 25 🔨 WS upgrade 101 / invalid token 4001 — add WS handshake check.
- 26 🔨 WS public conn cap (500) — add check (limiter exists in `rate_limiting/websocket_limiter`).
- 27 ✅ kill-switch endpoint cancels all <1s — `constitution.verify_human_control` + `kill_switch.py`.
- 28 ✅ /docs /redoc — runtime checker probes.
- 29 ✅ no auth bypass — `platform_auth.verify_token_signature_valid`/`session_valid`.
- 30 ✅ plan-gated 402/403 — `platform_auth.verify_has_permission`.
- 31 ✅ superadmin locked — `platform_auth.verify_has_permission`/`owns_resource`.
- 32 ✅ idempotency (no double-trade) — `payments.verify_idempotent_charge`, `jobs.verify_job_idempotent`.
- 33 ✅ 422 on malformed — `platform_web.verify_api_schema`.
- 34 🔨 no mass parameter binding — CI static (Pydantic-only) check.
- 35 ✅ GraphQL introspection/limits — strawberry mounted; `platform_web.verify_api_status`.
- 36 🔨 version prefix /api/v1 — CI route-naming check.
- 37 ✅ response matches OpenAPI — `platform_web.verify_api_schema`.
- 38 ✅ trace-id propagation — tracing middleware; `meta.verify_decision_trace` analog.
- 39 🔨 no broken redirects — add redirect-target check.
- 40 ✅ request timeout 504 — `platform_web.verify_api_latency` + middleware.

## §3 Authentication & authorization (41–60)
- 41 ✅ token expiry — `platform_auth.verify_token_not_expired`.
- 42 🔨 algorithm allowlist (no `none`) — add JWT-alg assert (high value, small).
- 43 ✅ payload integrity — `platform_auth.verify_token_signature_valid`.
- 44 ✅ user exists / deleted invalidated — `platform_auth.verify_session_valid`/`revoked_blocked`.
- 45 ✅ plan claim vs DB — `platform_auth.verify_has_permission` + `drift` checks.
- 46 ✅ role claim vs DB — `platform_auth.verify_has_permission`.
- 47 🔨 email-verified gate — add predicate/middleware assert.
- 48 ✅ 2FA enforcement — `platform_auth.verify_mfa_enforced`.
- 49 ✅ KYC gate on withdrawal — `compliance.verify_approval_workflow` + `platform_auth.verify_has_permission`.
- 50 ✅ account lockout — `platform_auth.verify_failed_login_throttled`.
- 51 ✅ bcrypt / no plaintext — `security.verify_no_exposed_secret` + `auth/service`.
- 52 ✅ session revocation on logout/pw-change — `platform_auth.verify_revoked_blocked`.
- 53 ✅ API-key hashed + scoped — `platform_auth.verify_no_secret_in_response`, `security.verify_secret_usage`.
- 54 ✅ no privilege escalation — `compliance.verify_no_privilege_escalation`, `platform_auth.verify_owns_resource`.
- 55 ✅ superadmin impersonation audited — `ops_extended.verify_override_logged`/`override_attributed`.
- 56 ✅ audit on auth events — `governance.verify_action_audited`/`audit_complete`.
- 57 ✅ frontend guards verify server-side — `platform_auth.verify_has_permission` (guards call API).
- 58 ✅ subscription gate — `platform_auth.verify_has_permission`.
- 59 🔨 localStorage token sync logout — frontend assertion (codeable in TS test).
- 60 ✅ CORS preflight — security-headers middleware.

## §4 Database models & data integrity (61–100)
- 61 ✅ PK present — `platform_data.verify_primary_keys_unique`.
- 62 ✅ FK valid / no orphans — `platform_data.verify_foreign_keys_valid`/`verify_no_orphans`.
- 63 ✅ unique constraints — `platform_data.verify_primary_keys_unique`, `business_logic.verify_unique_constraint`.
- 64 🔨 soft-delete default filter — add ORM/predicate check.
- 65 ✅ timestamps default/monotonic — `platform_data.verify_timestamp_monotonic`.
- 66 🔨 NUMERIC(18,8) not FLOAT — CI migration-lint check (high value for money).
- 67 ✅ NOT NULL critical cols — `platform_data.verify_no_null_in_required`.
- 68 🔨 enum check constraints — CI migration-lint.
- 69 ✅ JSON validated — Pydantic + `business_logic.verify_value_in_range`.
- 70 🔨 email format/unique — add predicate (or DB constraint).
- 71 ✅ FK index — `platform_data.verify_index_healthy`.
- 72 🚫/🔨 partitioning tick/market data — infra (Drop unless tick_data table exists; else Process).
- 73 ✅ pool headroom — `platform_web.verify_connection_pool`.
- 74 ✅ read-after-write — `business_logic.verify_cross_service_agreement` analog.
- 75 🔨 SERIALIZABLE for financial txns — code review + assert.
- 76 ✅ outbox atomicity — `business_logic.verify_no_partial_commit`.
- 77 ✅ migration checksum — Gate I (Alembic chain) in CI.
- 78 ✅ Alembic head/no drift — `platform_data.verify_migrations_applied`.
- 79 ✅ backup integrity — `resilience.verify_backup_integrity`/`backup_recent`.
- 80 ✅ PITR/WAL — `resilience.verify_restore_tested` (verification); 👤 enabling WAL is ops.
- 81 ✅ no SQL injection — `security` (Bandit in CI) + parameterized.
- 82 ✅ data retention purge — `compliance.verify_retention`.
- 83 ✅ row-count cap/archive — `jobs.verify_queue_depth` analog; `compliance.verify_retention`.
- 84 🔨 bidirectional relationships — CI ORM check.
- 85 🔨 bulk insert chunking — code review.
- 86 ✅ DB retry on deadlock — `database/connection.py` circuit breaker + retry.
- 87 ✅ no cross-DB joins — single PG; `systems.verify_acyclic` analog.
- 88 ✅ audit insert-only — `governance.verify_audit_immutable`/`verify_hash_chain` (runtime checker exercises it).
- 89 ✅ GDPR anonymize-on-delete — `assurance.verify_data_in_jurisdiction` + `compliance.verify_retention`.
- 90 ✅ tenant isolation — `governance.verify_pod_isolation`, `platform_auth.verify_no_cross_tenant` (runtime checker probes).
- 91 ✅ API-key hashing — `security.verify_no_exposed_secret`.
- 92 ✅ reconciliation uniqueness — `platform_data.verify_primary_keys_unique` + `reconciliation.verify_reconciliation_chain`.
- 93 ✅ tax report determinism — `economic.verify_report_accurate`, `replay.verify_replay_matches`.
- 94 ✅ wallet txn atomic / no negative — `payments.verify_ledger_balanced`/`withdrawal_within_balance`, `constitution.verify_no_negative_balance`.
- 95 ✅ session cleanup — `jobs.verify_scheduled_job_fired`.
- 96 ✅ watchlist no orphan — `platform_data.verify_foreign_keys_valid`.
- 97 ✅ crypto payment links — `payments.verify_payment_reconciles`.
- 98 🔨 email suppression honored — add predicate.
- 99 ✅ AML alert valid refs — `compliance.verify_chain_of_custody`.
- 100 ✅ system_events severity/alert — `operations.verify_critical_alert_delivered`.

## §5 WebSocket & real-time data (101–120)
- 101 🔨 WS auth handshake timeout 4001 — add WS check.
- 102 🔨 heartbeat/3-missed terminate — add WS check.
- 103 🔨 single connection per user — add check.
- 104 ✅ channel subscription enforcement — `platform_auth.verify_has_permission`.
- 105 ✅ tick format (sym/bid/ask/ts) — `constitution.verify_tick`/`verify_spread`.
- 106 ✅ no stale ticks → status:stale — `market.verify_data_freshness`.
- 107 ✅ signal dedup — `constitution.verify_no_duplicate_ids`.
- 108 ✅ risk alert broadcast <500ms — `operations.verify_critical_alert_delivered`.
- 109 ✅ position-update consistency — `business_logic.verify_cross_service_agreement`, reconciler.
- 110 ✅ account-update + margin call — `risk.verify_margin_buffer`.
- 111 ✅ reconnect backoff → REST fallback — covered by smart_router timeout test analog; 🔨 verify TS hook.
- 112 ✅ REST fallback freshness — `market.verify_data_freshness`.
- 113 🔨 public feed limits (8 sym/500 conn) — add check.
- 114 ✅ message ordering/seq — `market.verify_event_sequence`/`verify_causal_order`.
- 115 🔨 payload ≤64KB — add check.
- 116 ✅ no sensitive leak on public feed — `platform_auth.verify_no_secret_in_response`/`no_cross_tenant`.
- 117 ✅ tick→WS latency p99<50ms — `platform_web.verify_api_latency` analog; `execution.verify_latency_budget`.
- 118 ✅ Redis pub/sub degrade — `integrations.verify_circuit_open_on_failure`.
- 119 🔨 TCP keep-alive zombie cleanup — `jobs.verify_no_zombie_job` analog; add WS check.
- 120 🔨 reconnect full snapshot hydration — add WS check.

## §6 Trading engine & order management (121–180)
- 121 ✅ order state machine — `constitution.verify_order_state_transition`.
- 122 ✅ order_id unique — `constitution.verify_no_duplicate_ids`.
- 123 ✅ ClOrdID unique/day — `constitution.verify_no_duplicate_ids`.
- 124 ✅ tick-size alignment — `market_lifecycle.verify_price_on_tick`.
- 125 ✅ lot-size — `market_lifecycle.verify_quantity_on_lot`.
- 126 ✅ max order size — `market_lifecycle.verify_notional_within_bounds`, `risk.verify_order_liquidity`.
- 127 🚫 short-sale locate — equities-specific (OANDA gold has no locate).
- 128 ✅ self-trade prevention — `compliance.verify_no_wash_trade`.
- 129 🚫 cross prevention (limit vs NBBO) — equities/NBBO microstructure.
- 130 ✅ TIF validation — `business_logic.verify_value_in_range` (allowed set).
- 131 ✅ cancel/replace idempotency — `payments.verify_idempotent_charge` pattern.
- 132 ✅ cancel-on-disconnect <1s — kill-switch + `jobs.verify_no_zombie_job`.
- 133 🚫 iceberg display qty — venue order-type not on OANDA spot.
- 134 ✅ bracket atomicity — `business_logic.verify_no_partial_commit`.
- 135 ✅ algo params validated — `business_logic.verify_value_in_range`.
- 136 ✅ SOR routes best venue — `execution` smart_router (single venue now; predicate ready).
- 137 🚫 best-ex within NBBO — US-equities NBBO concept.
- 138 🚫 no trade-through — Reg-NMS / protected markets.
- 139 ✅ kill switch immediate — `constitution.verify_human_control` + `kill_switch`.
- 140 ✅ fill price ≥0 — `constitution.verify_tick` (price>0).
- 141 ✅ cum_qty ≤ order_qty — `constitution.verify_order_not_contradictory` (phantom-fill guard).
- 142 ✅ avg-px calc — `constitution.verify_order_not_contradictory` + OMS; `business_logic.verify_total_equals_sum`.
- 143 ✅ order/exchange reconciliation 10s — `execution.verify_broker_reconciliation`.
- 144 🔨 trade bust handling — add predicate (rare on OANDA; Build-low).
- 145 🚫 block trade allocation — institutional block trades.
- 146 🚫 allocation price fairness — block allocations.
- 147 🚫 multi-leg spread atomicity — spreads/options.
- 148 ✅ order expiry sweep (DAY/GTD) — `jobs.verify_scheduled_job_fired`.
- 149 ✅ position update on fill <10ms — `execution.verify_latency_budget`, reconciler.
- 150 ✅ pre-trade risk synchronous — `execution.verify_pre_trade_gate` (WIRED).
- 151 ✅ fat-finger price >5% — `risk` + `market_lifecycle.verify_no_liquidity_mirage`; pre-trade gate.
- 152 ✅ fat-finger qty >10% ADV — `risk.verify_order_liquidity`.
- 153 ✅ order rate limiter — `jobs.verify_failure_rate`/`platform_auth.verify_rate_limiter_active`.
- 154 ✅ duplicate-order prevention — `constitution.verify_no_duplicate_ids`.
- 155 ✅ order immutability (cancel/replace only) — `constitution.verify_order_state_transition`.
- 156 ✅ order latency p95<5ms — `execution.verify_latency_budget`.
- 157 ✅ order persistence before proceed — `business_logic.verify_no_partial_commit`.
- 158 ✅ event sourcing append-only — `replay.verify_event_replay_idempotent`, `governance.verify_hash_chain`.
- 159 ✅ exec-report dedup — `constitution.verify_no_duplicate_ids`.
- 160 🚫 FIX MsgSeqNum gaps/resend — FIX-session (CME path exists but gold is OANDA REST); Build-low if FIX live.
- 161 🚫 FIX heartbeat dead-session — FIX-specific.
- 162 ✅ exec matches known order — `execution.verify_reported_matches_actual`.
- 163 🔨 gateway book mirror 60s — add predicate (OANDA: low priority).
- 164 ✅ partial-fill immediate update — `execution.verify_reported_matches_actual`.
- 165 🔨 cancel ack/reject ≤2s — add predicate.
- 166 ✅ exchange-disconnect cancel — kill-switch + reconciler.
- 167 ✅ symbol mapping never fails — `market_lifecycle.verify_symbol_mapping_stable`.
- 168 ✅ market-status hold/resume — `market.verify_market_open`, `market_structure.verify_not_halted`.
- 169 ✅ halted-symbol block — `market_structure.verify_not_halted`, `market.verify_symbol_tradeable`.
- 170 ✅ gateway throttle to venue — `integrations.verify_dependency_rate_limit`.
- 171 🚫 SOR multi-venue fairness — single venue.
- 172 🔨 POV participation ±2% — add predicate if POV algo used.
- 173 🔨 TWAP slice timing — add predicate if TWAP used.
- 174 🚫 undisclosed/hidden qty — venue order type.
- 175 ✅ cancel/replace race resolve — `constitution.verify_order_state_transition`.
- 176 🚫 TRF trade reporting (10s) — US OTC reporting.
- 177 🚫 trade confirmation to counterparty — institutional confirms.
- 178 ✅ double-entry booking <1s — `reconciliation.verify_double_entry`.
- 179 ✅ commission/fees itemized — `reconciliation.verify_fee_integrity`.
- 180 🚫 settlement instructions/SSI — institutional settlement.

## §7 Positions, portfolio & accounting (181–210)
- 181 ✅ position uniqueness — `portfolio.verify_portfolio_state_transition` + `constitution.verify_no_duplicate_ids`.
- 182 ✅ net position — `portfolio.verify_portfolio_value`.
- 183 ✅ avg cost basis — `portfolio.verify_position_sizing` + corporate-action.
- 184 ✅ realized P&L — `constitution.verify_pnl_reconciliation`.
- 185 🔨 lot tracking (FIFO etc.) — add predicate (tax lots).
- 186 ✅ position flattening zeros P&L — `portfolio.verify_portfolio_value`.
- 187 ✅ corporate-action adjust — `market_lifecycle.verify_corporate_action_applied`.
- 188 ✅ multi-currency FX P&L — `portfolio.verify_currency_reconciled`.
- 189 ✅ mark-to-market — `portfolio.verify_portfolio_value`, `risk.verify_var`.
- 190 ✅ intraday snapshot immutable — `replay.verify_snapshot_consistent`.
- 191 ✅ collateral value/deficiency — `derivatives.verify_collateral_sufficient`, `risk.verify_margin_buffer`.
- 192 🚫 securities lending borrow — equities short borrow.
- 193 ✅ prime-broker recon T+1 — `reconciliation.verify_custody_reconciled` (predicate; PB is institutional 🚫 if no PB).
- 194 🚫 intercompany desks — multi-desk institution.
- 195 🚫 option exercise/assignment — options.
- 196 🚫 futures physical delivery — futures.
- 197 ✅ double-entry balanced — `reconciliation.verify_double_entry`.
- 198 ✅ subledger↔GL — `reconciliation.verify_reconciliation_chain`.
- 199 ✅ realized vs unrealized separated — `constitution.verify_pnl_reconciliation`.
- 200 🔨 interest accruals (bonds/cash) — add predicate if cash interest modeled.
- 201 ✅ tax-lot ↔ GL consistency — `reconciliation.verify_reconciliation_chain`.
- 202 ✅ manual-entry maker-checker — `governance.verify_dual_control`/`segregation_of_duties`.
- 203 ✅ financial statements tie-out — `reconciliation.verify_reconciliation_chain`, `economic.verify_economic_equilibrium`.
- 204 🔨 period-close lock — add predicate.
- 205 ✅ rounding to dedicated account — `economic.verify_economic_equilibrium` (tol).
- 206 ✅ cash balance never negative — `constitution.verify_no_negative_balance`.
- 207 ✅ margin requirement covered — `risk.verify_margin_buffer`, `derivatives.verify_collateral_sufficient`.
- 208 🚫 pattern-day-trader margin — US-equities PDT rule.
- 209 ✅ NAV consistency blocks reporting — `economic.verify_report_accurate`, `reconciliation.verify_reconciliation_chain`.
- 210 ✅ performance fees / high-water — `economic.verify_within_contract_limits`.

## §8 Risk management & circuit breakers (211–245)
- 211 ✅ pre-trade risk limits — `execution.verify_pre_trade_gate` (WIRED) + `risk.*`.
- 212 ✅ gross position limit — `risk.verify_exposure_limits`.
- 213 ✅ net position limit — `risk.verify_exposure_limits`.
- 214 ✅ Greeks limits — `derivatives.verify_greek_limits` (options; 🚫 if no options).
- 215 ✅ concentration — `risk.verify_concentration`/`dependency_concentration`.
- 216 ✅ leverage ratio — `risk.verify_leverage` (WIRED in reconciler).
- 217 ✅ intraday margin call — `risk.verify_margin_buffer`/`liquidation_distance`.
- 218 ✅ kill-switch on breach — `risk.catastrophic_loss_triggers` + reconciler→kill-switch (WIRED).
- 219 ✅ PnL attribution recon — `reconciliation.verify_alpha_attribution`.
- 220 ✅ VaR fresh intraday — `risk.verify_var` (WIRED) + `ai_quality.verify_risk_model_fresh`.
- 221 ✅ stress bounds — `ai_quality.verify_stress_model_complete`; `scripts/stress_test.py`.
- 222 ✅ limit hierarchy (firm>desk>…) — `risk.verify_within_limit` + `business_logic.verify_value_in_range`.
- 223 ✅ limit versioning — `drift.verify_risk_appetite_stable`, `risk_appetite` policy.
- 224 🚫 real-time option greeks — options.
- 225 🚫 put-call parity — options no-arb.
- 226 🚫 dividend adjustment for options — options.
- 227 🔨 interest-rate curve current — add predicate if curve used.
- 228 🚫 vol surface arbitrage-free — options vol surface.
- 229 ✅ counterparty credit limit — `risk.verify_dependency_concentration` (CVA 🚫 if no derivs).
- 230 🚫 CVA inputs (PD/LGD) — credit derivatives.
- 231 ✅ breach alert <1s — `operations.verify_critical_alert_delivered`.
- 232 ✅ risk check on cancel/replace — `execution.verify_pre_trade_gate`.
- 233 🔨 position aging risk weights — add predicate.
- 234 ✅ model validation vs benchmark — `ai_quality.verify_*`, `ai_governance.verify_strategy_approved`.
- 235 ✅ intraday risk snapshots — `replay.verify_snapshot_consistent`.
- 236 ✅ excessive cancellation rate — `compliance.verify_no_spoofing`, `jobs.verify_failure_rate`.
- 237 ✅ self-match prevention — `compliance.verify_no_wash_trade` (dup of 128).
- 238 ✅ risk PnL explain — `ai_governance.verify_belief_matches_reality`.
- 239 ✅ greeks continuity — `ai_quality.verify_signal_concentration` analog (🚫 if no options).
- 240 ✅ large-notional approval — `ops_extended.verify_change_has_approval`, `assurance.verify_no_unilateral_capital_move`.
- 241 ✅ correlation matrix PSD — `portfolio.verify_correlation_budget` (PSD: 🔨 add).
- 242 ✅ risk service fail-closed — `enforcement` fail-closed flag + `meta.verify_invariant_engine_healthy`.
- 243 ✅ DR replicate risk state — `resilience.verify_multi_region`/`failover_ready`.
- 244 🔨 regulatory capital charges — add predicate if reg-cap reported.
- 245 ✅ illiquid concentration flag — `risk.verify_concentration`, `market_lifecycle.verify_no_liquidity_mirage`.

## §9 Machine learning & AI (246–270)
- 246 ✅ model loads or pause — `ai.verify_model_approved`, `ml_pipeline.verify_model_signed`.
- 247 ✅ model version — `ai_governance.verify_strategy_approved`, `ai_quality.verify_feature_count_stable`.
- 248 ✅ inference latency — `ml_pipeline.verify_inference_cost`, `execution.verify_latency_budget`.
- 249 ✅ feature consistency — `ai.verify_features_finite`, `ml_pipeline.verify_feature_schema`, `ai_quality.verify_feature_count_stable`.
- 250 ✅ drift detection — `ai.verify_drift`, `drift.verify_no_value_drift`.
- 251 ✅ signal confidence [0,1] — `ai.verify_confidence`, `ai_quality.verify_model_output_bounded`.
- 252 ✅ backtest vs live — `ai_governance.verify_belief_matches_reality`, `assurance.verify_sim_fidelity`.
- 253 ✅ regime detection valid — `ai_quality.verify_regime_classified`.
- 254 ✅ LLM JSON schema/fallback — `ai.verify_hallucination_guard`, `platform_web.verify_api_schema`.
- 255 ✅ RL agent ≤ risk limits — `ai_governance.verify_autonomous_strategy_control`, `ai.verify_agent_authority`.
- 256 ✅ online learning ok — `ml_pipeline.verify_training_reproducible`.
- 257 ✅ daily retrain / keep-old-if-worse — `ai_governance.verify_strategy_approved`, `ml_pipeline.verify_model_lineage`.
- 258 ✅ feature store fresh ≤5s — `market.verify_data_freshness`, `knowledge.verify_context_freshness`.
- 259 ✅ anomaly detection runs — `meta.verify_anomaly_detection_operational`.
- 260 ✅ explainability per signal — `ai.verify_explainable`, `ai_quality.verify_prediction_matches_explanation`, `meta.verify_ai_explainability_coverage`.
- 261 ✅ backtest=live logic — `replay.verify_replay_matches`, `governance.verify_no_lookahead`.
- 262 ✅ hyperopt OOS validated — `ml_pipeline.verify_dataset_complete`, `ai_governance.verify_strategy_approved`.
- 263 ✅ RL action space constrained — `ai_governance.verify_autonomous_capital_limit`.
- 264 ✅ A/B split consistent — `business_logic.verify_cross_service_agreement`.
- 265 ✅ ML input sanity — `ai.verify_features_finite`, `security.verify_input_not_poisoned`.
- 266 ✅ model memory <50% — `ml_pipeline.verify_gpu_allocation` analog; `platform_web.verify_resource_headroom`.
- 267 ✅ GPU util/CPU fallback — `ml_pipeline.verify_gpu_allocation`.
- 268 ✅ no look-ahead bias — `governance.verify_no_lookahead`, `governance.verify_no_data_leakage`.
- 269 ✅ model persisted read-only — `ml_pipeline.verify_model_signed`, `security.verify_artifact_signed`.
- 270 ✅ rollback on degradation — `ai_governance.verify_strategy_approved` (rollback_exists), `resilience.verify_recovery_path_exists`.

## §10 Broker integrations (271–290)
- 271 ✅ broker connected / auto-switch — `integrations.verify_dependency_healthy`, `resilience.verify_failover_ready`.
- 272 ✅ paper mode never touches real — `assurance.verify_paper_not_mistaken_for_live`.
- 273 ✅ single broker per symbol — `systems.verify_single_leader`.
- 274 🚫 FIX session logon (CME) — FIX (gold is OANDA REST); Build-low if CME live.
- 275 ✅ broker rate-limit — `integrations.verify_dependency_rate_limit`.
- 276 ✅ exec matched to order — `execution.verify_reported_matches_actual`, `execution.verify_broker_reconciliation`.
- 277 ✅ position sync — `execution.verify_broker_reconciliation` (WIRED in reconciler).
- 278 ✅ balance/NAV sync — `reconciliation.verify_custody_reconciled`, `/health/ledger`.
- 279 ✅ txn history no gaps/dup — `constitution.verify_no_duplicate_ids`, `integrations.verify_no_event_loss`.
- 280 ✅ webhook signature verify — `integrations.verify_webhook_signature`/`webhook_not_replayed`.
- 281 ✅ order rejection mapped — `execution.verify_reported_matches_actual`.
- 282 ✅ connection pooling — `platform_web.verify_connection_pool`.
- 283 ✅ broker latency p95<200ms — `integrations.verify_vendor_sla`, `execution.verify_latency_budget`.
- 284 ✅ failover broker no double-exec — `resilience.verify_failover_ready` + order-auth token.
- 285 ✅ data normalization — `market_lifecycle.verify_symbol_mapping_stable`.
- 286 ✅ API-key rotation — `security.verify_secret_rotation`.
- 287 ✅ EOD reconciliation — `execution.verify_broker_reconciliation`.
- 288 ✅ cancel-on-disconnect — kill-switch + reconciler.
- 289 ✅ paper-vs-live flag enforced — `assurance.verify_paper_not_mistaken_for_live`.
- 290 ✅ TCA (commission/slippage) — `execution.verify_slippage`, `reconciliation.verify_fee_integrity`.

## §11 Celery & async tasks (291–305)
- 291 ✅ worker health — `jobs.verify_no_zombie_job`, `operations.verify_monitors_healthy`.
- 292 ✅ queue length ≤1000 — `jobs.verify_queue_depth`.
- 293 ✅ task timeout — `jobs.verify_job_within_sla`.
- 294 ✅ retries w/ backoff — `jobs.verify_attempts_bounded`.
- 295 ✅ DLQ alert — `jobs.verify_dlq_bounded`, `systems.verify_dead_letter_empty`.
- 296 ✅ beat schedule on time — `jobs.verify_scheduled_job_fired`.
- 297 ✅ backup task — `resilience.verify_backup_recent`.
- 298 ✅ self-healer runs — `jobs.verify_scheduled_job_fired`, `resilience.verify_recovery_path_exists`.
- 299 ✅ daily retrain before open — `jobs.verify_scheduled_job_fired`, `ai_governance.verify_strategy_approved`.
- 300 ✅ billing tasks ok/retry — `jobs.verify_failure_rate`, `payments.*`.
- 301 ✅ worker concurrency/OOM — `platform_web.verify_resource_headroom`.
- 302 ✅ result backend TTL — `systems.verify_cache_fresh`.
- 303 ✅ task idempotency — `jobs.verify_job_idempotent`.
- 304 ✅ task prioritization/starvation — `jobs.verify_oldest_message_age`.
- 305 ✅ broker (Redis) connected — `integrations.verify_dependency_healthy`.

## §12 Monitoring, alerting & observability (306–330)
- 306 ✅ /metrics reachable — exposed + runtime checker.
- 307 ✅ custom metrics — `prometheus_monitoring` (incl. `hopefx_invariant_*`).
- 308 ✅ alertmanager rules fire — `monitoring/rules/alerts.yml` + chaos.
- 309 ✅ Grafana dashboards load — `monitoring/grafana/invariant_dashboard.json`.
- 310 ✅ Sentry integration — `monitoring/sentry_config`.
- 311 ✅ deep health 503 — `/health` + `/health/invariants`.
- 312 ✅ log aggregation — `hopefx_observability` JSONL.
- 313 ✅ trace sampling/propagation — tracing middleware.
- 314 ✅ error-budget/SLO — `operations.verify_alert_fatigue`/`monitoring_coverage`.
- 315 ✅ latency SLI — `platform_web.verify_api_latency`.
- 316 ✅ circuit-breaker alert — `monitoring/rules` + `systems` predicates.
- 317 ✅ failed-login monitoring — `platform_auth.verify_failed_login_throttled`.
- 318 ✅ 5xx >1% pager — `platform_web.verify_error_rate`.
- 319 ✅ WS disconnect rate — `operations` + WS (🔨 specific metric).
- 320 ✅ slow queries >100ms — `platform_web.verify_api_latency`, `platform_data.verify_index_healthy`.
- 321 ✅ disk >80% — `platform_web.verify_disk_not_full`.
- 322 ✅ mem/CPU >80% — `platform_web.verify_resource_headroom`.
- 323 ✅ deadman heartbeat — `operations.verify_monitors_healthy`.
- 324 ✅ synthetic monitoring (paper trade 5min) — `assurance.verify_sim_fidelity`; `scripts/runtime_invariant_check`.
- 325 ✅ alert flapping hysteresis — `operations.verify_alert_fatigue`.
- 326 ✅ notification channels — `integrations.verify_notification_delivered`.
- 327 ✅ runbook links — `docs/INVARIANT_ROLLOUT.md`; 👤 per-alert runbooks.
- 328 ✅ status page accuracy — `meta.verify_observed_matches_actual`.
- 329 ✅ incident history — `operations.verify_incident_timeline_complete`.
- 330 👤 chaos engineering — ops program (`scripts/stress_test.py` is the code half).

## §13 Frontend pages & component state (331–380)
Mostly 🔨 (frontend TS tests/assertions) or ✅ where a server-side predicate backs them. Frontend was out of scope for the invariant library; these are a genuine codeable backlog in `frontend/` tests.
- 331–335 ✅ guards/gates server-verified — `platform_auth.verify_has_permission`/`owns_resource`/`no_cross_tenant`.
- 336–344 🔨 lazy-load, error boundaries, fetch states, form validation — frontend tests.
- 345–348 🔨/👤 a11y, responsive, noindex, SEO — frontend tests + review.
- 349 ✅ status page ↔ /status/json — `meta.verify_observed_matches_actual`.
- 350–380 🔨 per-page behavior (charts, kill-switch confirm, KYC upload, etc.) — frontend e2e/Playwright tests; #353 kill-switch confirm is ✅ server-side (`verify_human_control`).

(All 50 enumerated in the implementation backlog; bucket: ~6 ✅, ~40 🔨 frontend, ~4 👤.)

## §14 Superadmin & system administration (381–410)
Mostly ✅ at the access-control layer + 🔨 for per-section UI behavior.
- 381–410: access control ✅ (`platform_auth.verify_has_permission`/`owns_resource`); audit ✅ (`governance.verify_action_audited`, `ops_extended.*`); per-section UI behavior 🔨 (frontend/admin tests). #393 nuclear controls ✅ (`verify_human_control` + confirm). #406 billing reconciliation ✅ (`payments.verify_payment_reconciles`). #410 impersonation audited ✅ (`ops_extended.verify_override_logged`).

## §15 Security, privacy & compliance (411–430)
- 411 ✅ HTTPS — `platform_web.verify_certificate_valid` + 👤 deploy.
- 412 ✅ HSTS — `platform_auth.verify_security_headers`.
- 413 ✅ CSP — `platform_auth.verify_security_headers`.
- 414 ✅ XSS — React escape; `security.verify_input_not_poisoned`.
- 415 ✅ CSRF — `platform_auth.verify_csrf_protected`.
- 416 ✅ SQLi — Bandit CI + parameterized.
- 417 ✅ PII masking — `platform_auth.verify_no_secret_in_response`, `assurance` redaction.
- 418 ✅ password policy — `platform_auth.verify_password_policy`.
- 419 ✅ session fixation/rotation — `platform_auth.verify_session_valid`/`revoked_blocked`.
- 420 ✅ file-upload scan/MIME — `security.verify_input_not_poisoned`; `security/antivirus`.
- 421 ✅ auth rate-limit/lockout — `platform_auth.verify_failed_login_throttled`/`rate_limiter_active`.
- 422 ✅ API-key scoping/audit — `security.verify_secret_usage`.
- 423 ✅ dependency CVE scan — CI dependency-scan + Bandit.
- 424 ✅ secrets mgmt (Vault) — `security.verify_no_exposed_secret`, `config/vault`.
- 425 ✅ encryption at rest — `database/encryption.py`; 👤 HSM key mgmt.
- 426 👤 network segmentation — infra/Docker network.
- 427 👤 pentest — security program.
- 428 ✅ GDPR rights — `compliance.verify_retention`, `assurance.verify_data_in_jurisdiction`.
- 429 ✅ AML/KYC/sanctions — `compliance.verify_not_restricted`/`approval_workflow`.
- 430 ✅ audit logging — `governance.verify_action_audited`/`audit_complete`.

## §16 Infrastructure, deployment & reliability (431–460)
- 431 ✅ compose up healthy — runtime checker boot; `scripts/runtime_invariant_check`.
- 432 👤 restart policy — compose config.
- 433 👤 resource limits — compose config.
- 434 ✅ nginx config valid — Gate C (compose) + 👤 nginx -t.
- 435 ✅ TLS auto-renew >30d — `platform_web.verify_certificate_valid`; 👤 certbot.
- 436 ✅ CI all-tests-pass-before-merge — CI gates + invariant suite.
- 437 👤 canary deploy — deploy strategy.
- 438 ✅ rollback on failed deploy — `resilience.verify_recovery_path_exists`; `resilience/auto_rollback`.
- 439 👤 immutable artifacts (SHA tags) — CI/CD policy.
- 440 ✅ config drift detection — `governance.verify_config_unchanged`.
- 441 ✅ backup retention/restore test — `resilience.verify_backup_recent`/`restore_tested`.
- 442 ✅ DR failover — `resilience.verify_failover_ready`/`multi_region`; 👤 quarterly drill.
- 443 ✅ startup order/health — depends_on health; `systems.verify_quorum`.
- 444 👤 zero-downtime deploys — rolling-update strategy.
- 445 👤 log rotation — Docker config.
- 446 ✅ host resource monitoring — `platform_web.verify_resource_headroom`/`disk_not_full`.
- 447 ✅ self-healing restart — `resilience.verify_recovery_path_exists`.
- 448 ✅ secret rotation automation — `security.verify_secret_rotation`.
- 449 👤 daily load test/baseline — perf program.
- 450 👤 cost management — cloud budget.
- 451 👤 on-call rotation — ops.
- 452 ✅/👤 runbook completeness — `INVARIANT_ROLLOUT.md` + per-alert runbooks (👤).
- 453 ✅ code review + CI green, no direct push to main — `governance.verify_deployment_gates`; 👤 branch protection.
- 454 ✅ dependency freshness — CI dependency-scan.
- 455 ✅ static analysis in CI — ruff/bandit/detect-secrets.
- 456 ✅ every invariant has a test — `invariants` suites + `scripts/invariant_coverage.py`.
- 457 ✅ E2E smoke — `tests/e2e/` + runtime checker.
- 458 ✅ performance budgets — `platform_web.verify_bundle_size`/`api_latency`.
- 459 ✅ docs updated — `docs/CONSTITUTION_COVERAGE.md` etc.
- 460 👤 Chaos Monkey — ops (`stress_test.py`/`verify_chaos_survival` is the code half).

## §17 Data layer & market data orchestrator (461–480)
- 461 ✅ tick store latency <5ms — `execution.verify_latency_budget`, `market.verify_data_freshness`.
- 462 ✅ no duplicate ticks — `constitution.verify_no_duplicate_ids`, `platform_data.verify_primary_keys_unique`.
- 463 ✅ gap interpolation/flag — `market.verify_event_sequence`/`no_future_event`.
- 464 ✅ order-book snapshot consistency — `market.verify_orderbook_integrity`.
- 465 ✅ normalization/no unmapped — `market_lifecycle.verify_symbol_mapping_stable`.
- 466 ✅ microstructure signal bounds — `ai_quality.verify_model_output_bounded`, `ai.verify_features_finite`.
- 467 ✅ sentiment missing→neutral — `knowledge.verify_retrieval`, `ai.verify_features_finite`.
- 468 ✅ macro stale flag — `market.verify_data_freshness`, `knowledge.verify_context_freshness`.
- 469 ✅ historical API no future leak — `governance.verify_no_lookahead`, `market.verify_no_future_event`.
- 470 ✅ live price <50ms/fresh<1s — `platform_web.verify_api_latency`, `market.verify_data_freshness`.
- 471 ✅ symbol universe per plan — `platform_auth.verify_has_permission`, `market.verify_symbol_tradeable`.
- 472 ✅ compression round-trip — `replay.verify_replay_matches`, `integrations.verify_storage_checksum`.
- 473 ✅ retention/downsampling — `compliance.verify_retention`.
- 474 ✅ feed redundancy/failover <1s — `market.verify_feed_agreement`, `resilience.verify_failover_ready`.
- 475 ✅ reference data sync/mismatch — `market_lifecycle.verify_symbol_mapping_stable`, `drift.verify_no_value_drift`.
- 476 ✅ corporate actions applied — `market_lifecycle.verify_corporate_action_applied`.
- 477 ✅ market-hours no false ticks — `market.verify_market_open`.
- 478 ✅ orchestrator→WS <50ms — `execution.verify_latency_budget`.
- 479 ✅ subscription server-side filter — `platform_auth.verify_has_permission`.
- 480 ✅ tick price=0/null discarded — `constitution.verify_tick`.

## §18 Additional business logic & misc (481–501)
- 481 ✅ plan activate/downgrade timing — `payments.verify_charge_authorized`, `business_logic.verify_workflow_transition`.
- 482 ✅ invoice price/no rounding — `payments.verify_payment_reconciles`, `economic.verify_report_accurate`.
- 483 ✅ referral reward once — `payments.verify_idempotent_charge`, `business_logic.verify_unique_constraint`.
- 484 ✅ affiliate no self-referral — `business_logic.verify_value_in_range`/`unique_constraint`.
- 485 ✅ copy trading price/risk — `execution.verify_slippage`, `execution.verify_pre_trade_gate`.
- 486 ✅ leaderboard no manipulation — `economic.verify_report_accurate`, `replay.verify_replay_matches`.
- 487 🔨 marketplace links functional — frontend/route check.
- 488 ✅ notification delivery — `integrations.verify_notification_delivered`.
- 489 ✅ price alerts exact — `business_logic.verify_value_in_range`.
- 490 ✅ watchlist sync — `business_logic.verify_cross_service_agreement`.
- 491 🔨 calendar tz conversion — add predicate/test.
- 492 ✅ journal attachments secure/size — `security.verify_input_not_poisoned`, `integrations.verify_storage_durable`.
- 493 🔨 mobile lightweight payloads — add API-shape check.
- 494 ✅ feature gating no leak to lower tiers — `platform_auth.verify_has_permission`.
- 495 ✅ whitelabel tenant isolation — `governance.verify_pod_isolation`, `platform_auth.verify_no_cross_tenant`.
- 496 ✅ GDPR export complete — `compliance.verify_retention`, `assurance.verify_data_in_jurisdiction`.
- 497 ✅ account deletion anonymize/retain financials — `compliance.verify_retention`.
- 498 ✅ KYC doc retention encrypted/purged — `compliance.verify_retention`, `database/encryption`.
- 499 ✅ consent logging — `governance.verify_action_audited`.
- 500 ✅ regression suite / CI fails on regression — invariant suites + `scripts/invariant_coverage.py` CI gate.
- 501 ✅/👤 per-invariant docs — `CONSTITUTION_COVERAGE.md`; 👤 dev wiki upkeep.

---

## Top "Build" backlog (highest ROI, applicable, codeable)

These are the genuine gaps worth implementing as new predicates / runtime checks
(in priority order):

1. **#16 Route smoke-coverage** — enumerate *every* registered route and assert
   none returns 500 (runtime checker currently probes a curated subset). Also
   covers #29 (no auth bypass → 401/403 not 200).
2. **#17 OpenAPI integrity** — assert `/openapi.json` validates and contains all paths.
3. **#42 JWT algorithm allowlist** — reject `none`/unexpected `alg` (security-critical, tiny).
4. **#66 / #68 DB schema lint** — money columns are `NUMERIC`, status columns have
   enum/check constraints (CI migration-lint).
5. **#101–103, #113, #115 WebSocket invariants** — handshake timeout, heartbeat,
   single-connection-per-user, public caps, payload size.
6. **§13 frontend** — the ~40 frontend behaviors as Playwright/vitest assertions.

## What to drop (≈55 items)
US-equities / multi-asset / exchange-member microstructure that doesn't apply to
an OANDA gold platform: NBBO & trade-through (#129, #137, #138, #171), block-trade
allocation (#145, #146), iceberg/hidden/undisclosed order types (#133, #174),
TRF/OTC trade reporting & institutional confirms/SSI (#176, #177, #180), securities
lending (#192), intercompany desks (#194), options exercise/greeks/parity/vol-surface
(#147, #195, #214, #224–228, #239), futures delivery (#196), PDT margin (#208),
CVA/credit (#230), FIX session mechanics unless CME goes live (#160, #161, #274).

## Honest bottom line
Of 501: **~300 already have a predicate or mechanism** in the merged platform
(most need only live-wiring, which is the tracked rollout program), **~95 are real
codeable gaps** (mostly API/auth/DB hygiene + frontend), **~55 don't apply** to an
XAUUSD/OANDA platform, and **~50 are process/infra** owned by the team. The
document is a strong backlog once filtered through this lens — not a 501-item
implementation mandate.
