"""One resolved run mode, shared by the plan that is displayed and the code that runs.

`run.py` decided twice, on different conditions:

    _get_pipeline(mode)          # what the operator is SHOWN
        if mode == "paper" or PAPER_TRADING: ... paper pipeline

    main()                       # what actually RUNS
        if PAPER_TRADING or args.broker == "paper": PaperRunner
        else:                                       HopeFXEngine

`--mode paper` sets `OANDA_PRACTICE`, `BROKER`, `DEFAULT_BROKER` and
`INGEST_EXCHANGE` — never `PAPER_TRADING`. And the defaults are `--mode paper`
`--broker oanda`. So plain `python run.py` displayed the paper pipeline
(OandaPricePoll, TickSignalEngine, FIXRouter→PaperTradingBroker, FillRecorder)
and started HopeFXEngine, an entirely different subsystem set. Reproduced before
the fix::

    displayed pipeline is the paper one : True
    dispatch actually takes paper path  : False
    => runs: HopeFXEngine (LIVE engine)

It did NOT place real orders — `--mode paper` also sets `TRADING_MODE=paper`,
and `HopeFXEngine._execute_decision` returns at `if self.trading_mode != "live"`
before any broker call. That second control is what bounded this, and it is why
this is "the plan is not the system" rather than "it traded real money".

Two name collisions travel with it:

* `run.py` wrote `BROKER`; `brokers/factory.py` reads ``BROKER_TYPE or BROKER``,
  so an ambient `BROKER_TYPE` in `.env` silently overrode the explicit
  `--broker` flag.
* `--mode paper` forced `OANDA_PRACTICE=true`, but `brokers/oanda.py` reads
  `OANDA_ENVIRONMENT`, which nothing set — so the venue could be `live` while
  the run called itself paper.

M01 and M02 of an external source-inspection review, reproduced here.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _resolve(mode="paper", broker="oanda", **env):
    from core.run_mode import resolve_run_mode

    return resolve_run_mode(mode=mode, broker=broker, env=env)


class TestTheDisplayedPlanIsTheRunningPlan:
    def test_the_default_invocation_resolves_to_one_engine(self):
        """`python run.py` with no arguments: mode=paper, broker=oanda."""
        r = _resolve(mode="paper", broker="oanda")
        assert r.effective_mode == "paper"
        assert r.engine == "PaperRunner", "the default invocation displays the paper pipeline; it must also RUN it"

    @pytest.mark.parametrize("broker", ["oanda", "mt5", "ibkr", "binance", "alpaca", "paper"])
    def test_the_broker_flag_does_not_decide_the_engine(self, broker):
        """The engine follows the MODE. Keying it off `--broker == "paper"` is
        what made the two decisions disagree."""
        assert _resolve(mode="paper", broker=broker).engine == "PaperRunner"

    def test_live_mode_runs_the_live_engine(self):
        r = _resolve(mode="live", broker="oanda", OANDA_PRACTICE="false", OANDA_ENVIRONMENT="live")
        assert r.effective_mode == "live"
        assert r.engine == "HopeFXEngine"

    @pytest.mark.parametrize(("mode", "engine"), [("api", "api"), ("backtest", "backtest")])
    def test_non_trading_modes_run_neither_engine(self, mode, engine):
        assert _resolve(mode=mode, broker="oanda").engine == engine


class TestPaperTradingEnvStillForcesPaper:
    def test_the_env_flag_still_wins_for_paper(self):
        """Pre-existing behaviour: PAPER_TRADING=true forces the paper runner."""
        r = _resolve(mode="api", broker="oanda", PAPER_TRADING="true")
        assert r.engine == "PaperRunner"
        assert any("PAPER_TRADING" in reason for reason in r.reasons)

    def test_paper_trading_contradicting_live_mode_is_refused(self):
        r = _resolve(mode="live", broker="oanda", PAPER_TRADING="true")
        assert r.conflicts, "PAPER_TRADING=true with --mode live is a contradiction, not a preference"


class TestTheBrokerNameResolvesOnce:
    def test_the_explicit_flag_beats_an_ambient_broker_type(self):
        """`brokers/factory.py` reads BROKER_TYPE before BROKER, so writing only
        BROKER let `.env` override the command line."""
        r = _resolve(mode="live", broker="mt5", BROKER_TYPE="oanda", OANDA_PRACTICE="false", OANDA_ENVIRONMENT="live")
        assert r.broker == "mt5"
        assert r.env_overrides.get("BROKER_TYPE") == "mt5", (
            "the resolver must publish BROKER_TYPE too, or the factory will still pick the ambient value over the flag"
        )
        assert r.env_overrides.get("BROKER") == "mt5"


class TestTheVenueResolvesOnce:
    def test_paper_mode_sets_both_venue_names(self):
        """`OANDA_PRACTICE` and `OANDA_ENVIRONMENT` are read by different modules."""
        r = _resolve(mode="paper", broker="oanda")
        assert r.venue == "practice"
        assert r.env_overrides.get("OANDA_PRACTICE") == "true"
        assert r.env_overrides.get("OANDA_ENVIRONMENT") == "practice", (
            "brokers/oanda.py reads OANDA_ENVIRONMENT and never sees OANDA_PRACTICE"
        )

    def test_contradictory_venue_names_are_refused(self):
        r = _resolve(mode="live", broker="oanda", OANDA_PRACTICE="true", OANDA_ENVIRONMENT="live")
        assert r.conflicts, "OANDA_PRACTICE=true with OANDA_ENVIRONMENT=live names two venues"

    def test_a_non_oanda_broker_has_no_oanda_venue(self):
        assert _resolve(mode="paper", broker="mt5").venue is None


class TestTheResolutionExplainsItself:
    def test_every_resolution_carries_its_reasons(self):
        r = _resolve(mode="paper", broker="oanda")
        assert r.reasons, "a resolution with no stated reason cannot be audited"

    def test_a_conflict_names_both_sides(self):
        r = _resolve(mode="live", broker="oanda", PAPER_TRADING="true")
        assert any("PAPER_TRADING" in c and "live" in c for c in r.conflicts)

    def test_the_result_is_immutable(self):
        """The point of resolving once is that nothing downstream re-decides."""
        import dataclasses

        r = _resolve()
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.engine = "something else"  # type: ignore[misc]


class TestRunPyUsesOneDecision:
    """The resolver is only worth anything if `run.py` reads it twice — once to
    print the plan and once to start the system — instead of deciding twice."""

    def _args(self, mode, broker):
        import argparse
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location("runmod_e2e", "run.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules["runmod_e2e"] = m
        spec.loader.exec_module(m)
        return m, argparse.Namespace(mode=mode, broker=broker, config="prop_firm_mode.json")

    @pytest.mark.parametrize(
        ("mode", "broker"),
        [("paper", "oanda"), ("paper", "mt5"), ("paper", "paper"), ("live", "oanda")],
    )
    def test_the_printed_plan_matches_the_engine_that_would_run(self, mode, broker, monkeypatch):
        """The reproduction, asserted for every combination that used to diverge.

        `--mode paper --broker oanda` is plain `python run.py`: the defaults.
        Before the fix it printed the paper pipeline and started HopeFXEngine.
        """
        for name in ("PAPER_TRADING", "BROKER_TYPE", "OANDA_PRACTICE", "OANDA_ENVIRONMENT"):
            monkeypatch.delenv(name, raising=False)

        m, args = self._args(mode, broker)
        resolved = m.resolve_run_mode(mode=mode, broker=broker, env={}) if hasattr(m, "resolve_run_mode") else None
        if resolved is None:
            from core.run_mode import resolve_run_mode

            resolved = resolve_run_mode(mode=mode, broker=broker, env={})

        shown = m._get_pipeline(mode, engine=resolved.engine)
        shown_is_paper = any("PaperTrading" in s or "PAPER_TRADING=true" in s for s in shown)

        assert shown_is_paper == (resolved.engine == "PaperRunner"), (
            f"--mode {mode} --broker {broker}: the printed plan says paper={shown_is_paper} "
            f"while the resolved engine is {resolved.engine}"
        )

    def test_setup_env_publishes_broker_type(self, monkeypatch):
        """The collision that let `.env` beat the command line."""
        import os

        m, args = self._args("live", "mt5")
        # Explicit: another test in the same process may have left PAPER_TRADING
        # set, and PAPER_TRADING=true with --mode live is a refusal. Depending on
        # ambient environment is how this passed alone and failed in the suite.
        monkeypatch.delenv("PAPER_TRADING", raising=False)
        monkeypatch.setenv("BROKER_TYPE", "oanda")
        monkeypatch.setenv("OANDA_PRACTICE", "false")
        monkeypatch.setenv("OANDA_ENVIRONMENT", "live")

        m._setup_env(args)

        assert os.environ["BROKER_TYPE"] == "mt5", (
            "brokers/factory.py reads BROKER_TYPE before BROKER, so the ambient value would still win"
        )
        assert os.environ["BROKER"] == "mt5"

    def test_setup_env_publishes_both_venue_names(self, monkeypatch):
        import os

        m, args = self._args("paper", "oanda")
        monkeypatch.delenv("PAPER_TRADING", raising=False)
        monkeypatch.setenv("OANDA_ENVIRONMENT", "live")
        monkeypatch.delenv("OANDA_PRACTICE", raising=False)

        m._setup_env(args)

        assert os.environ["OANDA_PRACTICE"] == "true"
        assert os.environ["OANDA_ENVIRONMENT"] == "practice", (
            "brokers/oanda.py reads OANDA_ENVIRONMENT and never sees OANDA_PRACTICE"
        )

    def test_a_contradiction_refuses_to_start(self, monkeypatch):
        m, args = self._args("live", "oanda")
        monkeypatch.setenv("PAPER_TRADING", "true")

        with pytest.raises(SystemExit) as exc:
            m._setup_env(args)
        assert exc.value.code == 2, "a contradictory configuration must refuse, not pick a side"


class TestTheDocumentedModesAreTheRealModes:
    """`CLAUDE.md` and `AGENTS.md` both documented ``--mode api | engine |
    backtest``. ``engine`` has never been a mode::

        $ python run.py --mode engine
        error: argument --mode: invalid choice: 'engine'
               (choose from 'paper', 'live', 'api', 'backtest')

    An agent following the prose issues a command that cannot run, and the two
    files an agent is told to read first were the ones that said it. M05.
    """

    def _documented_modes(self, path: str) -> set[str]:
        import re
        from pathlib import Path

        text = Path(__file__).resolve().parents[2].joinpath(path).read_text(encoding="utf-8")
        # A pipe-separated list of lowercase words after `--mode`. Markdown
        # escapes the pipes inside a table cell (`\|`) and wraps the list in
        # backticks, so neither a closing paren nor a bare pipe can be relied on
        # as the terminator.
        found: set[str] = set()
        for match in re.finditer(r"--mode\s+([a-z]+(?:\s*\\?\|\s*[a-z]+)*)", text):
            found |= {m.strip(" \\") for m in match.group(1).split("|") if m.strip(" \\")}
        return found

    @pytest.mark.parametrize("path", ["CLAUDE.md", "AGENTS.md"])
    def test_no_document_names_a_mode_the_parser_rejects(self, path):
        from core.run_mode import MODES

        documented = self._documented_modes(path)
        assert documented, f"no --mode list found in {path} — this test would assert nothing"
        assert documented <= set(MODES), (
            f"{path} documents {sorted(documented - set(MODES))}, which `python run.py --mode` "
            f"refuses. Valid modes are {list(MODES)}"
        )

    def test_the_resolver_and_the_parser_agree_on_the_mode_list(self):
        """Two copies of the same list is how the last one drifted."""
        import importlib.util
        import sys

        from core.run_mode import MODES

        spec = importlib.util.spec_from_file_location("runmod_modes", "run.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules["runmod_modes"] = m
        spec.loader.exec_module(m)
        assert tuple(m.MODES) == tuple(MODES)


class TestApiAndBacktestDoNotClobberADeliberateTradingMode:
    """`--mode api` must not silently rewrite a deliberate `TRADING_MODE=live`.

    The pre-resolver `run.py` was explicit about this::

        # For api/backtest we preserve whatever the user configured in .env
        # (defaulting to the safe "paper") so launching the API server never
        # silently clobbers a deliberate TRADING_MODE=live.
        if args.mode in ("paper", "live"):
            os.environ["TRADING_MODE"] = args.mode
        else:
            os.environ.setdefault("TRADING_MODE", "paper")

    The first version of the resolver published `TRADING_MODE` unconditionally,
    so `--mode api` rewrote a configured `live` to `paper`. Safer-sounding and
    still wrong: it is the operator's setting, the API is the production serving
    process, and a deployment that quietly stops trading is as much a surprise
    as one that quietly starts.

    `TRADING_MODE` is the paper/live TRADING concept. The run mode is a
    different axis, and only the two trading run modes may pin it.
    """

    def test_api_mode_reports_a_configured_live_without_overriding_it(self):
        r = _resolve(mode="api", broker="oanda", TRADING_MODE="live")
        assert r.trading_mode == "live", "the resolution must report what is actually configured"
        assert "TRADING_MODE" not in r.env_overrides, (
            "publishing TRADING_MODE for api mode rewrites the operator's setting"
        )

    def test_backtest_mode_does_the_same(self):
        r = _resolve(mode="backtest", broker="oanda", TRADING_MODE="live")
        assert r.trading_mode == "live"
        assert "TRADING_MODE" not in r.env_overrides

    def test_api_mode_with_nothing_configured_is_paper(self):
        """The safe default survives — it just is not an override."""
        r = _resolve(mode="api", broker="oanda")
        assert r.trading_mode == "paper"

    @pytest.mark.parametrize("mode", ["paper", "live"])
    def test_the_two_trading_modes_still_pin_it(self, mode):
        """They are the modes that legitimately decide it."""
        env = {"TRADING_MODE": "live" if mode == "paper" else "paper"}
        if mode == "live":
            env |= {"OANDA_PRACTICE": "false", "OANDA_ENVIRONMENT": "live"}
        r = _resolve(mode=mode, broker="oanda", **env)
        assert r.env_overrides["TRADING_MODE"] == mode
        assert r.trading_mode == mode

    def test_setup_env_leaves_a_configured_trading_mode_alone(self, monkeypatch):
        import argparse
        import importlib.util
        import os
        import sys

        spec = importlib.util.spec_from_file_location("runmod_tm", "run.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules["runmod_tm"] = m
        spec.loader.exec_module(m)

        monkeypatch.delenv("PAPER_TRADING", raising=False)
        monkeypatch.setenv("TRADING_MODE", "live")
        m._setup_env(argparse.Namespace(mode="api", broker="oanda", config="prop_firm_mode.json"))

        assert os.environ["TRADING_MODE"] == "live", (
            "launching the API server rewrote a deliberate TRADING_MODE=live to paper"
        )
