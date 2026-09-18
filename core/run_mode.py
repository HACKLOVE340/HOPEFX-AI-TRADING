# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""One resolved run mode, shared by the plan that is displayed and the code that runs.

## Why this exists

`run.py` decided twice, on different conditions:

    _get_pipeline(mode)      # what the operator is SHOWN
        if mode == "paper" or PAPER_TRADING: ... the paper pipeline

    _run_trading(args)       # what actually RUNS
        if PAPER_TRADING or args.broker == "paper": PaperRunner
        else:                                       HopeFXEngine

`--mode paper` sets `OANDA_PRACTICE`, `BROKER`, `DEFAULT_BROKER` and
`INGEST_EXCHANGE` — never `PAPER_TRADING`. The defaults are `--mode paper` and
`--broker oanda`. So plain ``python run.py`` displayed the paper pipeline and
started `HopeFXEngine`, a different subsystem set entirely. An operator asking
why the TickSignalEngine was quiet was reading about a component that had never
been started, and an agent reasoning from the printed plan was reasoning about
the wrong system.

It did not place real orders: `--mode paper` also sets `TRADING_MODE=paper`, and
`HopeFXEngine._execute_decision` returns at ``if self.trading_mode != "live"``
before any broker call. That second, independent control is what bounded the
blast radius, and it is why this is "the plan is not the system" rather than
something worse. Depending on it was luck, not design.

## Two name collisions resolved here as well

* **Broker.** `run.py` wrote `BROKER`; `brokers/factory.py` reads
  ``BROKER_TYPE or BROKER``. An ambient `BROKER_TYPE` in `.env` therefore
  silently overrode the explicit `--broker` flag. The resolver publishes BOTH,
  so the flag wins because nothing is left to disagree with it.
* **Venue.** `--mode paper` forced `OANDA_PRACTICE=true`, but
  `brokers/oanda.py` reads `OANDA_ENVIRONMENT`, which nothing set. The resolver
  publishes both names from one decision, and refuses a configuration that names
  two different venues.

## The contract

`resolve_run_mode` is pure: it reads an explicit ``env`` mapping and returns a
frozen result. It mutates nothing, so it can be called before startup to
*display* the plan and again to *drive* it, and cannot give two answers.

`conflicts` being non-empty means refuse to start. A contradiction is not a
preference to resolve silently in one direction — whichever side a resolver
picks, somebody's stated intent is being ignored.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

#: Modes `run.py` accepts. Asserted equal to `run.py`'s own tuple by
#: tests/unit/test_run_mode_resolves_once.py — two copies of one list is how the
#: documented set drifted to include a mode that never existed.
MODES: Final[tuple[str, ...]] = ("paper", "live", "api", "backtest")

#: Brokers whose venue is named by the OANDA_* variables.
_OANDA_BROKERS: Final[frozenset[str]] = frozenset({"oanda"})

_TRUE: Final[frozenset[str]] = frozenset({"true", "1", "yes", "on"})


@dataclass(frozen=True)
class ResolvedRunMode:
    """What this run is, decided once.

    Frozen deliberately: the whole defect was two decisions disagreeing, so
    nothing downstream may adjust one field and leave the rest describing a
    different run.
    """

    requested_mode: str
    effective_mode: str
    #: PaperRunner | HopeFXEngine | api | backtest
    engine: str
    broker: str
    #: practice | live for an OANDA broker; None when the venue is not OANDA's
    #: to name.
    venue: str | None
    #: paper | live — whether orders from this run may be real. Distinct from
    #: `effective_mode`, which also covers api and backtest.
    trading_mode: str
    #: Environment variables this resolution implies. `run.py` publishes them so
    #: every module downstream reads one decision instead of re-deriving it from
    #: whichever name it happens to know.
    env_overrides: Mapping[str, str]
    reasons: tuple[str, ...] = field(default_factory=tuple)
    #: Non-empty means REFUSE TO START.
    conflicts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.conflicts


def _is_true(env: Mapping[str, str], name: str) -> bool:
    return str(env.get(name, "")).strip().lower() in _TRUE


def resolve_run_mode(
    *,
    mode: str,
    broker: str,
    env: Mapping[str, str] | None = None,
) -> ResolvedRunMode:
    """Resolve one run configuration from the CLI arguments and the environment.

    Pure. Returns the resolution and the environment it implies; the caller
    publishes it. See the module docstring for what each collision was.
    """
    env = dict(env or {})
    mode = (mode or "paper").strip().lower()
    broker = (broker or "oanda").strip().lower()

    reasons: list[str] = []
    conflicts: list[str] = []
    overrides: dict[str, str] = {}

    # ── Mode ─────────────────────────────────────────────────────────────────
    paper_env = _is_true(env, "PAPER_TRADING")
    effective = mode
    if paper_env and mode == "live":
        # Not a preference to resolve quietly: one of the two is wrong, and
        # picking either silently ignores a stated intent.
        conflicts.append("PAPER_TRADING=true but --mode live — refusing to guess which one you meant")
    elif paper_env and mode != "paper":
        effective = "paper"
        reasons.append(f"PAPER_TRADING=true in the environment overrides --mode {mode}")

    # ── Engine. Follows the MODE, never the broker flag ──────────────────────
    # Keying this off `args.broker == "paper"` is what let the displayed plan
    # and the dispatch disagree.
    engine = {
        "paper": "PaperRunner",
        "live": "HopeFXEngine",
        "api": "api",
        "backtest": "backtest",
    }.get(effective, "PaperRunner")
    reasons.append(f"mode {effective!r} selects {engine}")

    # TRADING_MODE is the paper/live TRADING concept; the run mode is a
    # different axis. Only the two trading run modes may PIN it. For api and
    # backtest the resolution REPORTS what is configured and publishes no
    # override — the first version of this resolver published it
    # unconditionally, so `--mode api` rewrote a deliberate TRADING_MODE=live to
    # paper. Safer-sounding and still wrong: it is the operator's setting, the
    # API is the production serving process, and a deployment that quietly
    # stops trading is as much a surprise as one that quietly starts. The
    # pre-resolver run.py said so in a comment; this restores it.
    if effective in ("paper", "live"):
        trading_mode = effective
        pins_trading_mode = True
    else:
        configured = str(env.get("TRADING_MODE", "")).strip().lower()
        trading_mode = configured if configured in ("paper", "live") else "paper"
        pins_trading_mode = False
        if configured in ("paper", "live"):
            reasons.append(f"TRADING_MODE={configured!r} is the operator's, and {effective} mode leaves it alone")

    # ── Broker. The explicit flag wins because nothing is left to disagree ───
    ambient = str(env.get("BROKER_TYPE", "")).strip().lower()
    if ambient and ambient != broker:
        reasons.append(f"BROKER_TYPE={ambient!r} in the environment is overridden by --broker {broker!r}")
    overrides["BROKER"] = broker
    overrides["BROKER_TYPE"] = broker
    overrides["DEFAULT_BROKER"] = broker

    # ── Venue ────────────────────────────────────────────────────────────────
    venue: str | None = None
    if broker in _OANDA_BROKERS:
        practice_set = "OANDA_PRACTICE" in env
        environment_set = "OANDA_ENVIRONMENT" in env
        from_practice = "practice" if _is_true(env, "OANDA_PRACTICE") else "live"
        from_environment = str(env.get("OANDA_ENVIRONMENT", "")).strip().lower() or None

        if practice_set and environment_set and from_environment != from_practice:
            conflicts.append(
                f"OANDA_PRACTICE={env.get('OANDA_PRACTICE')!r} and "
                f"OANDA_ENVIRONMENT={from_environment!r} name two different venues"
            )

        if effective == "paper":
            venue = "practice"
            reasons.append("paper mode pins the OANDA venue to practice")
        elif environment_set and from_environment in ("practice", "live"):
            venue = from_environment
        elif practice_set:
            venue = from_practice
        else:
            venue = "practice"
            reasons.append("no OANDA venue configured — defaulting to practice")

        # Published under BOTH names: brokers/oanda.py reads OANDA_ENVIRONMENT,
        # brokers/oanda_stream.py and brokers/manager.py read OANDA_PRACTICE.
        overrides["OANDA_PRACTICE"] = "true" if venue == "practice" else "false"
        overrides["OANDA_ENVIRONMENT"] = venue

    if pins_trading_mode:
        overrides["TRADING_MODE"] = trading_mode

    return ResolvedRunMode(
        requested_mode=mode,
        effective_mode=effective,
        engine=engine,
        broker=broker,
        venue=venue,
        trading_mode=trading_mode,
        env_overrides=overrides,
        reasons=tuple(reasons),
        conflicts=tuple(conflicts),
    )
