# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_feed_missing_api_keys.py
========================================
An enabled data source with no API key must say so at startup.

``AlphaVantageSource`` and ``TwelveDataSource`` both skip every fetch when
``api_key`` is empty, and they do it at DEBUG level::

    if not self._api_key:
        logger.debug("TwelveDataSource: no API key — skipping %s", symbol)
        return None

At normal log levels that is indistinguishable from an upstream outage, and
both look like "no data" in the UI.

It matters most for the metals. XAUUSD, XAGUSD and XPTUSD carry no
``yfinance_ticker`` on purpose — Yahoo delisted spot, and the config records
that quoting GLD (~$390) against spot gold (~$4,070) "would be far worse than
no quote at all". So those three can only be priced by the two keyed sources.
Without a key there is no spot gold on a platform whose primary instrument is
gold, and nothing anywhere says why.
"""

from __future__ import annotations

import logging

import pytest

pytestmark = pytest.mark.unit


def _write_config(tmp_path, *, av_enabled=True, td_enabled=True) -> str:
    """Minimal feed config on disk — the constructor takes a path, not a dict."""
    import yaml

    cfg = {
        "multi_source_feed": {
            "symbols": {
                # No yfinance ticker — the keyed sources are the only option.
                "XAUUSD": {
                    "yfinance_ticker": "",
                    "alpha_vantage_symbol": "XAU",
                    "twelve_data_symbol": "XAU/USD",
                    "price_min": 1000.0,
                    "price_max": 10000.0,
                },
                # Has a yfinance ticker — unaffected by a missing key.
                "EURUSD": {
                    "yfinance_ticker": "EURUSD=X",
                    "twelve_data_symbol": "EUR/USD",
                    "price_min": 0.5,
                    "price_max": 2.0,
                },
            },
            "alpha_vantage": {"enabled": av_enabled, "api_key": ""},
            "twelve_data": {"enabled": td_enabled, "api_key": ""},
            "yfinance": {"enabled": True},
        }
    }
    path = tmp_path / "feed.yaml"
    path.write_text(yaml.safe_dump(cfg))
    return str(path)


def _feed(monkeypatch, tmp_path, *, av: str = "", td: str = "", **kw):
    """Build a MultiSourceTickFeed with the given keys and no real network."""
    for var in ("ALPHA_VANTAGE_KEY", "ALPHA_VANTAGE_API_KEY", "TWELVE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    if av:
        monkeypatch.setenv("ALPHA_VANTAGE_KEY", av)
    if td:
        monkeypatch.setenv("TWELVE_API_KEY", td)

    from data_feed.multi_source_feed import MultiSourceTickFeed

    return MultiSourceTickFeed(config_path=_write_config(tmp_path, **kw))


def test_missing_keys_are_reported_at_warning_level(monkeypatch, tmp_path, caplog):
    feed = _feed(monkeypatch, tmp_path)

    with caplog.at_level(logging.WARNING, logger="data_feed.multi_source_feed"):
        feed._build_sources()

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "an enabled source with no key was not reported at WARNING"
    joined = " ".join(warnings)
    assert "alpha_vantage" in joined and "twelve_data" in joined
    # The operator must be told which variable to set...
    assert "ALPHA_VANTAGE_KEY" in joined
    assert "TWELVE_API_KEY" in joined
    # ...and which symbols go dark as a result.
    assert "XAUUSD" in joined
    # EURUSD has a yfinance fallback, so it is not affected.
    assert "EURUSD" not in joined


def test_no_warning_when_both_keys_are_present(monkeypatch, tmp_path, caplog):
    feed = _feed(monkeypatch, tmp_path, av="av-key", td="td-key")

    with caplog.at_level(logging.WARNING, logger="data_feed.multi_source_feed"):
        feed._build_sources()

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_only_the_unconfigured_source_is_named(monkeypatch, tmp_path, caplog):
    """A half-configured feed must not imply both sources are broken."""
    feed = _feed(monkeypatch, tmp_path, td="td-key")

    with caplog.at_level(logging.WARNING, logger="data_feed.multi_source_feed"):
        feed._build_sources()

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "alpha_vantage" in joined
    assert "twelve_data" not in joined
    assert "ALPHA_VANTAGE_KEY" in joined


def test_a_disabled_source_is_not_reported(monkeypatch, tmp_path, caplog):
    """Deliberately switching a source off is not a misconfiguration."""
    feed = _feed(monkeypatch, tmp_path, av_enabled=False, td_enabled=False)

    with caplog.at_level(logging.WARNING, logger="data_feed.multi_source_feed"):
        feed._build_sources()

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize("source_cls,name", [
    ("AlphaVantageSource", "alpha_vantage"),
    ("TwelveDataSource", "twelve_data"),
])
async def test_keyless_source_returns_none_without_calling_out(source_cls, name):
    """The skip must be a clean None, not a doomed HTTP request per tick."""
    import importlib

    mod = importlib.import_module(f"data_feed.sources.{name}")
    cls = getattr(mod, source_cls)

    result = await cls(api_key="").fetch(
        "XAUUSD", {"alpha_vantage_symbol": "XAU", "twelve_data_symbol": "XAU/USD"}
    )
    assert result is None


def test_metals_have_no_yfinance_fallback_in_the_real_config():
    """Pins the dependency this warning exists for.

    If someone later gives the metals a yfinance ticker, that is a deliberate
    decision about quoting a proxy for spot — it should not happen by accident.
    """
    import re
    from pathlib import Path

    cfg = (Path(__file__).resolve().parents[2] / "config" / "multi_source_feed.yaml").read_text()

    for metal in ("XAUUSD", "XAGUSD", "XPTUSD"):
        block = re.search(rf"^    {metal}:\n(.*?)(?=^    [A-Z]|\Z)", cfg, re.S | re.M)
        assert block, f"{metal} missing from the feed config"
        ticker = re.search(r'yfinance_ticker:\s*"([^"]*)"', block.group(1))
        assert ticker and ticker.group(1) == "", (
            f"{metal} gained a yfinance ticker — Yahoo serves no spot price for it, "
            "so this would quote a futures contract or ETF as spot."
        )


# ── _resolve_env ──────────────────────────────────────────────────────────────
# The feed config accepts either variable name via a NESTED default:
#   api_key: "${ALPHA_VANTAGE_KEY:${ALPHA_VANTAGE_API_KEY:}}"
# The resolver partitioned on ":" once and returned the default verbatim, so
# with neither set it yielded the literal string "${ALPHA_VANTAGE_API_KEY:}".
# Being truthy, that string was then used AS the API key: the `or os.getenv(...)`
# fallbacks were skipped, an unset key looked configured, and every fetch sent
# `apikey=${ALPHA_VANTAGE_API_KEY:}` upstream — one guaranteed-failing request
# per symbol per cycle.

def test_nested_placeholder_resolves_to_empty_when_nothing_is_set(monkeypatch):
    from data_feed.multi_source_feed import _resolve_env

    monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

    resolved = _resolve_env("${ALPHA_VANTAGE_KEY:${ALPHA_VANTAGE_API_KEY:}}")

    assert resolved == "", f"unset key resolved to {resolved!r}, which would be sent upstream"
    assert not resolved, "an unset key must be falsy so the caller treats it as unconfigured"


def test_nested_placeholder_falls_back_to_the_second_name(monkeypatch):
    from data_feed.multi_source_feed import _resolve_env

    monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "from-second")

    assert _resolve_env("${ALPHA_VANTAGE_KEY:${ALPHA_VANTAGE_API_KEY:}}") == "from-second"


def test_primary_name_wins_over_the_fallback(monkeypatch):
    from data_feed.multi_source_feed import _resolve_env

    monkeypatch.setenv("ALPHA_VANTAGE_KEY", "from-primary")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "from-second")

    assert _resolve_env("${ALPHA_VANTAGE_KEY:${ALPHA_VANTAGE_API_KEY:}}") == "from-primary"


@pytest.mark.parametrize(("template", "expected"), [
    ("${NO_SUCH_VAR:plain-default}", "plain-default"),
    ("${NO_SUCH_VAR:}", ""),
    ("${NO_SUCH_VAR}", ""),
    ("literal-value", "literal-value"),
])
def test_simple_placeholder_forms_are_unchanged(monkeypatch, template, expected):
    """The single-level behaviour callers already rely on must not regress."""
    from data_feed.multi_source_feed import _resolve_env

    monkeypatch.delenv("NO_SUCH_VAR", raising=False)
    assert _resolve_env(template) == expected


def test_pathological_nesting_terminates(monkeypatch):
    """A malformed config must not spin the resolver."""
    from data_feed.multi_source_feed import _resolve_env

    monkeypatch.delenv("A", raising=False)
    deep = "${A:" * 20 + "}" * 20
    assert _resolve_env(deep) == ""


def test_the_real_config_resolves_to_empty_without_env(monkeypatch):
    """End to end: the shipped config must not manufacture a fake key."""
    import yaml
    from pathlib import Path

    from data_feed.multi_source_feed import _resolve_env

    for var in ("ALPHA_VANTAGE_KEY", "ALPHA_VANTAGE_API_KEY", "TWELVE_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    cfg = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "config" / "multi_source_feed.yaml").read_text()
    )["multi_source_feed"]

    for source in ("alpha_vantage", "twelve_data"):
        raw = cfg.get(source, {}).get("api_key", "")
        assert _resolve_env(raw) == "", (
            f"{source}.api_key resolved to a non-empty value with no environment set — "
            "that value would be sent to the provider as an API key"
        )
