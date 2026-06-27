# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Tests for phase 11-21 generic-platform invariant modules (platform_web,
platform_data, platform_auth, payments, jobs, business_logic, ai_quality,
market_lifecycle, ops_extended, assurance, integrations).

Each invariant is proven to PASS on valid input and CATCH the violation.
"""

import pytest

from invariants import (
    ai_quality as aiq,
    assurance as asr,
    business_logic as biz,
    integrations as integ,
    jobs,
    market_lifecycle as mkl,
    ops_extended as ops2,
    payments as pay,
    platform_auth as auth,
    platform_data as pdata,
    platform_web as web,
)

pytestmark = pytest.mark.unit


def test_platform_web():
    assert web.verify_service_up(True) == []
    assert web.verify_service_up(False)
    assert web.verify_uptime(99.99, 99.9) == []
    assert web.verify_uptime(98.0, 99.9)
    assert web.verify_error_rate(0.001, 0.01) == []
    assert web.verify_error_rate(0.5, 0.01)
    assert web.verify_restart_count(1, 5) == []
    assert web.verify_restart_count(20, 5)
    assert web.verify_no_console_errors(0) == []
    assert web.verify_no_console_errors(3)
    assert web.verify_page_renders(True) == []
    assert web.verify_page_renders(False)
    assert web.verify_page_load_time(800, 2000) == []
    assert web.verify_page_load_time(5000, 2000)
    assert web.verify_web_vital("LCP", 1.5, 2.5) == []
    assert web.verify_web_vital("LCP", 5.0, 2.5)
    assert web.verify_bundle_size(400, 1000) == []
    assert web.verify_bundle_size(3000, 1000)
    assert web.verify_api_status(200) == []
    assert web.verify_api_status(500)
    assert web.verify_api_schema({"a": 1, "b": 2}, {"a", "b"}) == []
    assert web.verify_api_schema({"a": 1}, {"a", "b"})
    assert web.verify_api_latency(120, 500) == []
    assert web.verify_api_latency(2000, 500)
    assert web.verify_api_version_supported("v2", {"v1", "v2"}) == []
    assert web.verify_api_version_supported("v0", {"v1", "v2"})
    assert web.verify_resource_headroom(40, 90) == []
    assert web.verify_resource_headroom(99, 90)
    assert web.verify_disk_not_full(40, 10) == []
    assert web.verify_disk_not_full(5, 10)
    assert web.verify_connection_pool(5, 100) == []
    assert web.verify_connection_pool(100, 100)
    assert web.verify_certificate_valid(60, 14) == []
    assert web.verify_certificate_valid(5, 14)
    assert web.verify_certificate_valid(-1, 14)


def test_platform_data():
    assert pdata.verify_primary_keys_unique([1, 2, 3]) == []
    assert pdata.verify_primary_keys_unique([1, 2, 2])
    assert pdata.verify_foreign_keys_valid([1, 2], {1, 2, 3}) == []
    assert pdata.verify_foreign_keys_valid([1, 9], {1, 2, 3})
    assert pdata.verify_no_orphans(0) == []
    assert pdata.verify_no_orphans(4)
    assert pdata.verify_referential_integrity(0) == []
    assert pdata.verify_referential_integrity(2)
    assert pdata.verify_migrations_applied([1, 2, 3], [1, 2, 3]) == []
    assert pdata.verify_migrations_applied([1, 2], [1, 2, 3])
    assert pdata.verify_index_healthy(5, 30) == []
    assert pdata.verify_index_healthy(60, 30)
    assert pdata.verify_cache_matches_db(5, 5) == []
    assert pdata.verify_cache_matches_db(5, 7)
    assert pdata.verify_search_matches_db({1, 2}, {1, 2}) == []
    assert pdata.verify_search_matches_db({1}, {1, 2})
    assert pdata.verify_replica_lag(1, 10) == []
    assert pdata.verify_replica_lag(60, 10)
    assert pdata.verify_rollup_matches_source(100.0, 100.0) == []
    assert pdata.verify_rollup_matches_source(100.0, 90.0)
    assert pdata.verify_no_null_in_required({"a": 1, "b": 2}, ["a", "b"]) == []
    assert pdata.verify_no_null_in_required({"a": 1, "b": None}, ["a", "b"])
    assert pdata.verify_timestamp_monotonic([1, 2, 3]) == []
    assert pdata.verify_timestamp_monotonic([1, 3, 2])


def test_platform_auth():
    assert auth.verify_token_signature_valid(True) == []
    assert auth.verify_token_signature_valid(False)
    assert auth.verify_token_not_expired(100, 200) == []
    assert auth.verify_token_not_expired(200, 100)
    assert auth.verify_session_valid(True, revoked=False) == []
    assert auth.verify_session_valid(False)
    assert auth.verify_session_valid(True, revoked=True)
    assert auth.verify_password_policy(12, 8) == []
    assert auth.verify_password_policy(4, 8)
    assert auth.verify_password_policy(12, 8, has_complexity=False)
    assert auth.verify_mfa_enforced(True, True) == []
    assert auth.verify_mfa_enforced(True, False)
    assert auth.verify_revoked_blocked("k1", {"k2"}) == []
    assert auth.verify_revoked_blocked("k1", {"k1"})
    assert auth.verify_owns_resource("u1", "u1") == []
    assert auth.verify_owns_resource("u1", "u2")
    assert auth.verify_has_permission("read", ["read", "write"]) == []
    assert auth.verify_has_permission("admin", ["read"])
    assert auth.verify_no_cross_tenant("t1", "t1") == []
    assert auth.verify_no_cross_tenant("t1", "t2")
    assert auth.verify_no_secret_in_response({"name": "x", "count": 1}) == []
    assert auth.verify_no_secret_in_response({"password": "x"})
    assert auth.verify_rate_limiter_active(True) == []
    assert auth.verify_rate_limiter_active(False)
    good_headers = {
        "content-security-policy": "x",
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "strict-transport-security": "max-age=1",
    }
    assert auth.verify_security_headers(good_headers) == []
    assert auth.verify_security_headers({"content-security-policy": "x"})
    assert auth.verify_csrf_protected(True, True) == []
    assert auth.verify_csrf_protected(True, False)
    assert auth.verify_failed_login_throttled(2, 5) == []
    assert auth.verify_failed_login_throttled(20, 5)


def test_payments():
    assert pay.verify_charge_authorized(True, 10) == []
    assert pay.verify_charge_authorized(False, 10)
    assert pay.verify_idempotent_charge("k1", ["k2"]) == []
    assert pay.verify_idempotent_charge("k1", ["k1"])
    assert pay.verify_amount_valid(10.0) == []
    assert pay.verify_amount_valid(-1.0)
    assert pay.verify_amount_valid(float("nan"))
    assert pay.verify_refund_within_original(5, 10) == []
    assert pay.verify_refund_within_original(15, 10)
    assert pay.verify_total_refunds_within_original([3, 4], 10) == []
    assert pay.verify_total_refunds_within_original([6, 6], 10)
    assert pay.verify_ledger_balanced(100, 100) == []
    assert pay.verify_ledger_balanced(100, 90)
    assert pay.verify_balance_after(100, -30, 70) == []
    assert pay.verify_balance_after(100, -30, 80)
    assert pay.verify_currency_consistent("USD", "USD") == []
    assert pay.verify_currency_consistent("USD", "EUR")
    assert pay.verify_payment_reconciles(100, 100) == []
    assert pay.verify_payment_reconciles(100, 95)
    assert pay.verify_withdrawal_within_balance(50, 100) == []
    assert pay.verify_withdrawal_within_balance(150, 100)


def test_jobs():
    assert jobs.verify_job_within_sla(10, 60) == []
    assert jobs.verify_job_within_sla(120, 60)
    assert jobs.verify_scheduled_job_fired(24, 24) == []
    assert jobs.verify_scheduled_job_fired(24, 20)
    assert jobs.verify_queue_depth(10, 1000) == []
    assert jobs.verify_queue_depth(5000, 1000)
    assert jobs.verify_oldest_message_age(5, 300) == []
    assert jobs.verify_oldest_message_age(600, 300)
    assert jobs.verify_dlq_bounded(0, 10) == []
    assert jobs.verify_dlq_bounded(50, 10)
    assert jobs.verify_job_idempotent("j1", ["j2"]) == []
    assert jobs.verify_job_idempotent("j1", ["j1"])
    assert jobs.verify_no_zombie_job(10, 300) == []
    assert jobs.verify_no_zombie_job(600, 300)
    assert jobs.verify_attempts_bounded(2, 5) == []
    assert jobs.verify_attempts_bounded(10, 5)
    assert jobs.verify_no_concurrent_singleton(1) == []
    assert jobs.verify_no_concurrent_singleton(3)
    assert jobs.verify_failure_rate(1, 100, 0.1) == []
    assert jobs.verify_failure_rate(50, 100, 0.1)


def test_business_logic():
    allowed = {"draft": ["submitted"], "submitted": ["approved", "rejected"]}
    assert biz.verify_workflow_transition("draft", "submitted", allowed) == []
    assert biz.verify_workflow_transition("draft", "approved", allowed)
    assert biz.verify_quantity_conserved(100, 70, -30) == []
    assert biz.verify_quantity_conserved(100, 80, -30)
    assert biz.verify_total_equals_sum(10.0, [4, 6]) == []
    assert biz.verify_total_equals_sum(10.0, [4, 5])
    assert biz.verify_count_matches(5, 5) == []
    assert biz.verify_count_matches(5, 4)
    assert biz.verify_value_in_range(5, 0, 10) == []
    assert biz.verify_value_in_range(50, 0, 10)
    assert biz.verify_discount_bounded(10, 50) == []
    assert biz.verify_discount_bounded(90, 50)
    assert biz.verify_unique_constraint([1, 2, 3]) == []
    assert biz.verify_unique_constraint([1, 1, 2])
    assert biz.verify_cross_service_agreement({"a": 5, "b": 5}) == []
    assert biz.verify_cross_service_agreement({"a": 5, "b": 7})
    assert biz.verify_no_partial_commit([True, True, True]) == []
    assert biz.verify_no_partial_commit([True, False, True])
    assert biz.verify_invariant_count_stable(10, 10) == []
    assert biz.verify_invariant_count_stable(10, 11)


def test_ai_quality():
    assert aiq.verify_feature_count_stable(50, 50) == []
    assert aiq.verify_feature_count_stable(40, 50)
    assert aiq.verify_feature_sparsity(0.1, 0.5) == []
    assert aiq.verify_feature_sparsity(0.9, 0.5)
    assert aiq.verify_regime_classified(0.9, 0.6) == []
    assert aiq.verify_regime_classified(0.3, 0.6)
    assert aiq.verify_signal_concentration([0.2, 0.3, 0.1], 0.5) == []
    assert aiq.verify_signal_concentration([0.9, 0.1], 0.5)
    assert aiq.verify_trade_not_clustered(3, 10) == []
    assert aiq.verify_trade_not_clustered(100, 10)
    assert aiq.verify_explanation_consistent("a", "a") == []
    assert aiq.verify_explanation_consistent("a", "b")
    assert aiq.verify_prediction_matches_explanation("BUY", "BUY") == []
    assert aiq.verify_prediction_matches_explanation("BUY", "SELL")
    assert aiq.verify_risk_model_fresh(10, 300) == []
    assert aiq.verify_risk_model_fresh(600, 300)
    assert aiq.verify_stress_model_complete(["a", "b"], ["a", "b"]) == []
    assert aiq.verify_stress_model_complete(["a"], ["a", "b"])
    assert aiq.verify_model_output_bounded(0.5, 0, 1) == []
    assert aiq.verify_model_output_bounded(2.0, 0, 1)
    assert aiq.verify_model_output_bounded(float("inf"), 0, 1)
    assert aiq.verify_calibration_error({"x": 0.5}, {"x": 0.52}, 0.1) == []
    assert aiq.verify_calibration_error({"x": 0.1}, {"x": 0.9}, 0.1)


def test_market_lifecycle():
    assert mkl.verify_price_on_tick(100.25, 0.25) == []
    assert mkl.verify_price_on_tick(100.13, 0.25)
    assert mkl.verify_quantity_on_lot(300, 100) == []
    assert mkl.verify_quantity_on_lot(150, 100)
    assert mkl.verify_notional_within_bounds(5000, 100, 100000) == []
    assert mkl.verify_notional_within_bounds(50, 100, 100000)
    assert mkl.verify_notional_within_bounds(500000, 100, 100000)
    assert mkl.verify_corporate_action_applied(True) == []
    assert mkl.verify_corporate_action_applied(False)
    assert mkl.verify_symbol_mapping_stable("XAUUSD", "XAUUSD") == []
    assert mkl.verify_symbol_mapping_stable("XAUUSD", "XAGUSD")
    assert mkl.verify_instrument_tradable(True, False) == []
    assert mkl.verify_instrument_tradable(True, True)
    assert mkl.verify_instrument_tradable(False, False)
    assert mkl.verify_settlement_date_valid(True) == []
    assert mkl.verify_settlement_date_valid(False)
    assert mkl.verify_tax_applied(10.0, 10.0) == []
    assert mkl.verify_tax_applied(10.0, 5.0)
    assert mkl.verify_no_liquidity_mirage(100, 95, 0.2) == []
    assert mkl.verify_no_liquidity_mirage(100, 10, 0.2)
    assert mkl.verify_position_within_exchange_limit(50, 100) == []
    assert mkl.verify_position_within_exchange_limit(150, 100)


def test_ops_extended():
    assert ops2.verify_alert_escalated(10, 300, False) == []
    assert ops2.verify_alert_escalated(600, 300, False)
    assert ops2.verify_alert_escalated(600, 300, True) == []
    assert ops2.verify_incident_has_root_cause(True, "db oom") == []
    assert ops2.verify_incident_has_root_cause(True, None)
    assert ops2.verify_postmortem_complete(3, 3, True) == []
    assert ops2.verify_postmortem_complete(3, 3, False)
    assert ops2.verify_override_logged(True, True) == []
    assert ops2.verify_override_logged(True, False)
    assert ops2.verify_override_attributed(True, "alice") == []
    assert ops2.verify_override_attributed(True, None)
    assert ops2.verify_override_authorized("admin", {"admin"}) == []
    assert ops2.verify_override_authorized("guest", {"admin"})
    assert ops2.verify_override_rate_bounded(1, 5) == []
    assert ops2.verify_override_rate_bounded(50, 5)
    assert ops2.verify_retired_strategy_stopped(True, False) == []
    assert ops2.verify_retired_strategy_stopped(True, True)
    assert ops2.verify_emergency_governance("ciso", "ciso") == []
    assert ops2.verify_emergency_governance("intern", "ciso")
    assert ops2.verify_change_has_approval(True, "alice") == []
    assert ops2.verify_change_has_approval(True, None)


def test_assurance():
    assert asr.verify_sim_fidelity(100, 102, 10) == []
    assert asr.verify_sim_fidelity(100, 200, 10)
    assert asr.verify_paper_not_mistaken_for_live("paper", False) == []
    assert asr.verify_paper_not_mistaken_for_live("paper", True)
    assert asr.verify_paper_not_mistaken_for_live("live", False)
    assert asr.verify_data_in_jurisdiction("eu", {"eu", "us"}) == []
    assert asr.verify_data_in_jurisdiction("cn", {"eu", "us"})
    assert asr.verify_no_cross_region_leak("eu", "eu") == []
    assert asr.verify_no_cross_region_leak("eu", "us")
    assert asr.verify_no_unilateral_capital_move(100000, ["a", "b"], 2) == []
    assert asr.verify_no_unilateral_capital_move(100000, ["a"], 2)
    assert asr.verify_least_privilege(["read"], ["read", "write"]) == []
    assert asr.verify_least_privilege(["read", "admin"], ["read"])
    assert asr.verify_dual_control(True, 2) == []
    assert asr.verify_dual_control(True, 1)
    assert asr.verify_access_reviewed(30, 90) == []
    assert asr.verify_access_reviewed(200, 90)
    assert asr.verify_anomalous_access_blocked(0.2, 0.8, False) == []
    assert asr.verify_anomalous_access_blocked(0.95, 0.8, False)
    assert asr.verify_anomalous_access_blocked(0.95, 0.8, True) == []


def test_integrations():
    assert integ.verify_dependency_healthy(True) == []
    assert integ.verify_dependency_healthy(False)
    assert integ.verify_dependency_rate_limit(50, 1000) == []
    assert integ.verify_dependency_rate_limit(1000, 1000)
    assert integ.verify_vendor_sla(100, 500) == []
    assert integ.verify_vendor_sla(2000, 500)
    assert integ.verify_webhook_signature(True) == []
    assert integ.verify_webhook_signature(False)
    assert integ.verify_webhook_not_replayed("e1", ["e2"]) == []
    assert integ.verify_webhook_not_replayed("e1", ["e1"])
    assert integ.verify_notification_delivered(100, 100, 5) == []
    assert integ.verify_notification_delivered(100, 50, 5)
    assert integ.verify_storage_durable(3, 2) == []
    assert integ.verify_storage_durable(1, 2)
    assert integ.verify_storage_checksum("abc", "abc") == []
    assert integ.verify_storage_checksum("abc", "xyz")
    assert integ.verify_pipeline_fresh(10, 300) == []
    assert integ.verify_pipeline_fresh(600, 300)
    assert integ.verify_no_event_loss(100, 100) == []
    assert integ.verify_no_event_loss(100, 90)
    assert integ.verify_circuit_open_on_failure(0.1, 0.5, False) == []
    assert integ.verify_circuit_open_on_failure(0.9, 0.5, False)
    assert integ.verify_circuit_open_on_failure(0.9, 0.5, True) == []
