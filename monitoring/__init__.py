# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
monitoring package
==================
Observability stack for HOPEFX:

  sentry_config   — Sentry SDK init, PII scrubbing, ML fallback alerts,
                    kill-switch alerts, paper-clock alerts, Sharpe gate alerts.

The prometheus.yml and rules/ directory in this folder are Prometheus
configuration files (not Python modules) — they are consumed by the
Prometheus Docker container, not imported by Python.
"""
