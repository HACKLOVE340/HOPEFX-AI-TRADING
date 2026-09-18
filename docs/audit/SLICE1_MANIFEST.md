# Slice 1 — measurement & gates — proven green 2026-09-18

Cut from c6c8fb0 onto origin/main. 128 files. 19 gates enforced.
Proof: 554 passed, 1 skipped, 0 failed; all 6 script-backed hooks exit 0.

## Gates enforced in this slice (19)
  gate_a_auth_coverage
  gate_b_env_consistency
  gate_broken_imports
  gate_c_docker_compose
  gate_d_model_accuracy
  gate_e_dead_files
  gate_f_doc_consistency
  gate_g_import_discipline
  gate_h_wordmap_schema
  gate_i_migration_chain
  gate_k_requirements_consistency
  gate_l_safety_invariants
  gate_m_ml_edge
  check-secrets
  docs-registry
  group4-index
  group4-preservation
  healer-check
  correction-register

## Files

### root (2)
  .coveragerc
  .pre-commit-config.yaml

### scripts/ (45)
  scripts/adr.py
  scripts/aos_conformance.py
  scripts/api_documentation_generator.py
  scripts/backlog_report.py
  scripts/bootstrap_dev.py
  scripts/capability_callers.py
  scripts/check_secrets.sh
  scripts/ci/gate_a_auth_coverage.py
  scripts/ci/gate_chroma_embedded_only.py
  scripts/ci/gate_e_dead_files.py
  scripts/ci/gate_f_doc_consistency.py
  scripts/ci/gate_g_import_discipline.py
  scripts/ci/gate_j_circular_imports.py
  scripts/ci/gate_k_requirements_consistency.py
  scripts/ci/gate_m_ml_edge.py
  scripts/clamp_ohlc.py
  scripts/correction_register.py
  scripts/coverage_scope_report.py
  scripts/diagnose_deploy.sh
  scripts/doc_metrics.py
  scripts/docs_freshness.py
  scripts/docs_registry.py
  scripts/drift_guard_report.py
  scripts/e2e_production_validation.py
  scripts/fetch_hand_model.py
  scripts/gate_evidence.py
  scripts/group4_index.py
  scripts/group4_preservation.py
  scripts/install.ps1
  scripts/install.sh
  scripts/install_ollama.ps1
  scripts/install_ollama.sh
  scripts/invariant_coverage.py
  scripts/make_swipe_y4m.py
  scripts/model_artifact_manifest_gate.py
  scripts/model_provenance_report.py
  scripts/pre_commit_coverage.py
  scripts/predict_offline.py
  scripts/retrain_horizon5.py
  scripts/retrain_model.py
  scripts/scan_git_history_for_secrets.py
  scripts/schema_migration_check.py
  scripts/spatial_capabilities.py
  scripts/verify_skill_claims.py
  scripts/vps_capability_report.py

### tests/ (24)
  tests/unit/test_adr_gate_injections.py
  tests/unit/test_adr_outcome_ledger.py
  tests/unit/test_api_endpoint_doc_is_generated.py
  tests/unit/test_backlog_report.py
  tests/unit/test_bootstrap_installs_hooks.py
  tests/unit/test_check_secrets_injections.py
  tests/unit/test_correction_register_gate.py
  tests/unit/test_coverage_gate_says_why_it_could_not_measure.py
  tests/unit/test_coverage_report_does_not_claim_verification.py
  tests/unit/test_docs_registry.py
  tests/unit/test_gate_a_resolves_auth_aliases.py
  tests/unit/test_gate_b_env_injections.py
  tests/unit/test_gate_c_docker_compose_injections.py
  tests/unit/test_gate_d_model_accuracy_injections.py
  tests/unit/test_gate_e_dead_files_injections.py
  tests/unit/test_gate_f_doc_consistency_injections.py
  tests/unit/test_gate_g_import_discipline_injections.py
  tests/unit/test_gate_h_wordmap_schema_injections.py
  tests/unit/test_gate_i_migration_injections.py
  tests/unit/test_gate_k_requirements_injections.py
  tests/unit/test_gate_l_safety_injections.py
  tests/unit/test_gate_m_ml_edge_injections.py
  tests/unit/test_group4_index.py
  tests/unit/test_group4_preservation.py

### docs/ (57)
  docs/COVERAGE_UNMEASURABLE.txt
  docs/FRESHNESS_BASELINE.toml
  docs/GATE_EVIDENCE.toml
  docs/REGISTRY.toml
  docs/ai/MASTER_OUTSTANDING.md
  docs/ai/specs/AOS_INVARIANT_REGISTER.toml
  docs/ai/specs/GROUP1_advanced_intelligence_architecture.txt
  docs/ai/specs/GROUP23_brief.txt
  docs/ai/specs/GROUP2_platform_engineering_operations_governance.md
  docs/ai/specs/GROUP3_documentation_knowledge_architecture_governance.md
  docs/ai/specs/GROUP4_CONSTITUTION.md
  docs/ai/specs/GROUP4_VOLUME_INDEX.md
  docs/ai/specs/GROUP4_master_ai_operating_system.txt
  docs/ai/specs/GROUP4_master_ai_operating_system_v2_complete.txt
  docs/ai/specs/SPATIAL_CAPABILITIES.toml
  docs/ai/specs/SPATIAL_INTELLIGENCE.md
  docs/audit/CORRECTION_REGISTER.md
  docs/decisions/0001-pin-python-to-3-12.md
  docs/decisions/0002-commit-model-artefacts-and-the-built-dashboard.md
  docs/decisions/0003-prop-firm-config-is-tracked-with-placeholders.md
  docs/decisions/0004-delegation-is-bounded-three-ways.md
  docs/decisions/0005-a-grant-crosses-the-process-boundary.md
  docs/decisions/0006-3d-is-not-webgl-and-must-earn-its-place.md
  docs/decisions/0007-the-landmark-model-is-not-vendored.md
  docs/decisions/0008-operational-intelligence-stays-in-group-1.md
  docs/decisions/0009-the-camera-was-there-all-along.md
  docs/decisions/0010-where-the-decision-ledger-lives-and-why-it-is-not-a-second-audit-log.md
  docs/decisions/0011-the-risk-tier-is-derived-from-paths-until-the-package-register-exists.md
  docs/decisions/0012-the-change-record-gate-warns-rather-than-blocks.md
  docs/decisions/0013-data-owns-streaming-data-layer-owns-access.md
  docs/decisions/0014-slow-and-e2e-tests-run-nightly.md
  docs/decisions/0015-adopt-embedding-based-news-sentiment.md
  docs/decisions/0016-root-documents-are-authoritative.md
  docs/decisions/0017-an-incomplete-coverage-baseline-may-be-extended-under-four-conditions.md
  docs/decisions/0018-a-module-unit-tests-import-may-not-be-excluded-from-coverage.md
  docs/decisions/0019-drift-blocking-model-quality-blocking-and-the-z-threshold.md
  docs/decisions/0020-the-decision-ledger-is-a-second-artefact.md
  docs/decisions/README.md
  docs/decisions/outcomes/0001.md
  docs/decisions/outcomes/0002.md
  docs/decisions/outcomes/0003.md
  docs/decisions/outcomes/0004.md
  docs/decisions/outcomes/0005.md
  docs/decisions/outcomes/0006.md
  docs/decisions/outcomes/0007.md
  docs/decisions/outcomes/0008.md
  docs/decisions/outcomes/0009.md
  docs/decisions/outcomes/0010.md
  docs/decisions/outcomes/0011.md
  docs/decisions/outcomes/0012.md
  docs/decisions/outcomes/0013.md
  docs/decisions/outcomes/0014.md
  docs/decisions/outcomes/0015.md
  docs/decisions/outcomes/0016.md
  docs/decisions/outcomes/0017.md
  docs/decisions/outcomes/0018.md
  docs/decisions/outcomes/0020.md
