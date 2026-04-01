import re

# (file, line_number, old_text, new_text)
fixes = [
    # --- Prometheus optional metrics (7) ---
    ("risk/intra_trade_monitor.py", 74, "except Exception:", "except Exception:  # nosec B110 — Prometheus metrics optional"),
    ("risk/post_trade_analyzer.py", 78, "except Exception:", "except Exception:  # nosec B110 — Prometheus metrics optional"),
    ("chaos/injector.py", 76, "except Exception:", "except Exception:  # nosec B110 — Prometheus metrics optional"),
    ("execution/order_algorithms.py", 63, "except Exception:", "except Exception:  # nosec B110 — Prometheus metrics optional"),
    ("compliance/regulatory_reporter.py", 111, "except Exception:", "except Exception:  # nosec B110 — Prometheus metrics optional"),
    ("shadow/trading_engine.py", 75, "except Exception:", "except Exception:  # nosec B110 — Prometheus metrics optional"),
    ("shadow/data_validator.py", 79, "except Exception:", "except Exception:  # nosec B110 — Prometheus metrics optional"),

    # --- JSON/parse errors ---
    ("brokers/oanda_paper_clock.py", 109, "except Exception:", "except (ValueError, KeyError):"),
    ("brokers/oanda_paper_clock.py", 137, "except Exception:", "except (ValueError, TypeError):"),
    ("core/email_webhook.py", 118, "except Exception:", "except (ValueError, TypeError):"),
    ("deployment/challenge_launch.py", 373, "except Exception:", "except (ValueError, OSError):"),
    ("data/tick_feed.py", 286, "except Exception:", "except (ValueError, TypeError):"),
    ("data_layer/feeds/news/newsdata.py", 67, "except Exception:", "except (ValueError, TypeError):"),
    ("data_layer/feeds/news/alpha_vantage.py", 72, "except Exception:", "except (ValueError, TypeError):"),
    ("data_layer/feeds/news/fmp.py", 69, "except Exception:", "except (ValueError, TypeError):"),
    ("api/payments.py", 371, "except Exception:", "except (ValueError, TypeError):"),
    ("security/global_fortress.py", 715, "except Exception:", "except (ValueError, TypeError):"),
    ("data_layer/normalization/pipeline.py", 185, "except Exception:", "except (ValueError, TypeError):"),
    ("ml/pipeline.py", 680, "except Exception:", "except (ValueError, TypeError):"),
    ("ml/train_with_macro.py", 489, "except Exception:", "except (ValueError, TypeError):"),
    ("research/pipeline/models_deep.py", 714, "except Exception:", "except (ValueError, TypeError):"),
    ("research/vector_store.py", 189, "except Exception:", "except (ValueError, TypeError):"),
    ("analysis/patterns/support_resistance.py", 431, "except Exception:", "except (AttributeError, TypeError):"),
    ("cache/market_data_cache.py", 491, "except Exception:", "except (KeyError, TypeError, ValueError):"),
    ("cache/market_data_cache.py", 566, "except Exception:", "except (KeyError, TypeError, ValueError):"),
    ("security/encryption.py", 134, "except Exception:", "except (ValueError, UnicodeDecodeError):"),

    # --- Network/IO/Redis resilience ---
    ("core/event_bus.py", 475, "except Exception:", "except Exception:  # nosec B110 — Redis reconnect resilience"),
    ("auth/service.py", 70, "except Exception:", "except Exception:  # nosec B110 — Redis optional, in-memory fallback"),
    ("api/platform.py", 630, "except Exception:", "except Exception:  # nosec B110 — Redis optional for rate limiter"),
    ("api/status.py", 59, "except Exception:", "except Exception:  # nosec B110 — Redis optional"),

    # --- Intentional resilience / fallback ---
    ("resilience/circuit_breaker.py", 76, "except Exception:", "except Exception:  # nosec B110 — record failure before re-raise"),
    ("brokers/ibkr_connector.py", 550, "except Exception:", "except Exception:  # nosec B110 — fallback to zero on ticker error"),
    ("core/health.py", 72, "except Exception:", "except Exception:  # nosec B110 — health-check availability probe"),
    ("ml/rl_agent.py", 443, "except Exception:", "except Exception:  # nosec B110 — default confidence on prediction error"),
    ("ml/advanced_predictor.py", 161, "except Exception:", "except Exception:  # nosec B110 — return None on prediction failure"),
    ("ml/live_inference.py", 581, "except Exception:", "except Exception:  # nosec B110 — optional macro features"),
    ("ml/macro_features.py", 425, "except Exception:", "except Exception:  # nosec B110 — numerical fallback for Hurst exponent"),
    ("ml/advanced_features.py", 771, "except Exception:", "except Exception:  # nosec B110 — numerical fallback for Hurst exponent"),
    ("ml/model_registry.py", 178, "except Exception:", "except Exception:  # nosec B110 — cleanup temp file before re-raise"),
    ("brain/llm_agent.py", 270, "except Exception:", "except Exception:  # nosec B110 — close fd before re-raise"),
    ("risk/manager.py", 470, "except Exception:", "except Exception:  # nosec B110 — graceful degradation without drawdown tracker"),
    ("risk/compliance/prop_engine.py", 312, "except Exception:", "except Exception:  # nosec B110 — callback error logged below"),
    ("risk/pre_trade_gate.py", 435, "except Exception:", "except Exception:  # nosec B110 — optional CVaR computation"),
    ("research/pipeline/regime_models.py", 396, "except Exception:", "except Exception:  # nosec B110 — joblib fallback to pickle"),
    ("research/pipeline/orchestrator.py", 679, "except Exception:", "except Exception:  # nosec B110 — regime prediction fallback"),
    ("config/config_manager.py", 309, "except Exception:", "except Exception:  # nosec B110 — return raw value on decrypt failure"),
    ("data_layer/lineage/store.py", 610, "except Exception:", "except Exception:  # nosec B110 — graceful count fallback"),
    ("visualization/dashboard.py", 54, "except Exception:", "except Exception:  # nosec B110 — remove disconnected WebSocket client"),
    ("dashboard/web_dashboard.py", 74, "except Exception:", "except Exception:  # nosec B110 — track disconnected WebSocket client"),
    ("api/broker.py", 376, "except Exception:", "except Exception:  # nosec B110 — fallback to empty status"),
    ("examples/generate_proof_artifacts.py", 237, "except Exception:", "except Exception:  # nosec B110 — numerical fallback for Hurst exponent"),
]

applied = 0
errors = []

for filepath, lineno, old, new in fixes:
    try:
        with open(filepath, 'r') as f:
            lines = f.readlines()
        
        idx = lineno - 1
        if idx < 0 or idx >= len(lines):
            errors.append(f"{filepath}:{lineno} - line out of range")
            continue
        
        line = lines[idx]
        if old not in line:
            errors.append(f"{filepath}:{lineno} - '{old}' not found in line: {line.rstrip()}")
            continue
        
        lines[idx] = line.replace(old, new, 1)
        
        with open(filepath, 'w') as f:
            f.writelines(lines)
        
        applied += 1
    except Exception as e:
        errors.append(f"{filepath}:{lineno} - {e}")

print(f"Applied: {applied}/{len(fixes)}")
if errors:
    print("Errors:")
    for e in errors:
        print(f"  {e}")
