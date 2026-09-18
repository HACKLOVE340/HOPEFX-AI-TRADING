# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The local model runtime — started with the application, honest about itself.

Owner requirement, 2026-09-06 (plan §1A.5.1): the local LLM and any other local
models must come up **at application startup**, so they are running on the VPS
without anyone starting them by hand.

Nothing did this before. Every part of the local path assumed an Ollama server
that was already listening with the model already pulled, which after a reboot
or a fresh deploy it is not. `scripts/vps_capability_report.py` has documented
this module as the thing that reads `LOCAL_MODEL_TIER` since it was written; the
module did not exist, so that was a reference to nothing.

The sharp edge this closes is in `ai/gateway/providers.py`:

    "ollama": ("OLLAMA_BASE_URL",)
    def local_inference_enabled() -> bool:
        return is_credentialed("ollama")     # True because a STRING IS SET

An environment variable is not evidence that a server is listening on the other
end of it. `is_ready()` here probes instead, so "the local leg can answer" is a
measurement rather than a claim.

Five properties, each one load-bearing:

**Off by default.** Upgrading a deployment must not start downloading a model.

**Never blocks startup.** `init_local_model_runtime` puts `start()` on a
background task, the same shape as `init_hourly_trainer`. The trading engine
does not wait on a model download.

**Never starts a model the machine cannot hold.** The capability report says
why, and it is worth repeating because it is a trading argument rather than a
tidiness one: "an oversized model does not degrade, it fails to load or swaps
the box to a standstill." On a machine that also executes orders, swapping to a
standstill is an outage. So the runtime measures RAM and VRAM and refuses a tier
that does not fit, rather than trying and finding out.

**Failure is never fatal and never silent.** Every failure path returns a status
carrying the refusal and logs at ERROR — not DEBUG, which is off in production
and is how four alert call sites in this repository failed silently for months.

**The status describes what happened.** `started` is set from the result of the
work, never before it, and a model that failed to pull appears in
`models_failed` rather than being quietly absent.

Every external effect — probing, launching, pulling, measuring — is injected, so
the tests exercise the real decision logic without touching the network, a
subprocess, or /proc.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import subprocess  # nosec B404 - fixed argv, no shell; see _default_launch/_default_pull
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

#: Environment variables. Named here so the report script, the tests and the
#: startup factory all spell them the same way. The Ollama base URL is
#: deliberately NOT among them: `ai/gateway`'s adapter owns how a provider is
#: reached, and a second copy of that default here is exactly the drift this
#: module removed from scripts/vps_capability_report.py.
AUTOSTART_ENV: Final = "LOCAL_MODEL_AUTOSTART"
TIER_ENV: Final = "LOCAL_MODEL_TIER"
MODELS_ENV: Final = "LOCAL_MODEL_NAMES"
#: Whether the runtime may INSTALL Ollama when it is missing.
#:
#: Off by default, and that is a decision rather than an oversight: installing
#: software is not something an application does to a trading box on its own.
#: `scripts/install.sh` and `scripts/install.ps1` install it at deploy time,
#: which is where a person is present to see it happen.
AUTO_INSTALL_ENV: Final = "LOCAL_MODEL_AUTO_INSTALL"

DEFAULT_LOCAL_MODEL: Final = "llama3"
DEFAULT_TIER: Final = "1B-4B"

#: (tier, minimum RAM GiB, minimum VRAM GiB) from AI_CORE_SPEC §8.
#:
#: A zero minimum means that resource alone cannot buy the tier: the top three
#: rows are GPU tiers, so no amount of system RAM qualifies for them. This is
#: the canonical copy — `scripts/vps_capability_report.py` imports it rather
#: than keeping a second one, because two tables drift and the drift would be
#: invisible until a model failed to load on a live box.
TIERS: Final[tuple[tuple[str, float, float], ...]] = (
    ("70B+", 0, 80),
    ("30B+", 0, 48),
    ("13B-14B", 0, 24),
    ("7B-8B", 16, 8),
    ("1B-4B", 8, 0),
)

#: How long to wait for a server we just launched to answer, and how often to ask.
READINESS_TIMEOUT_S: Final = 90.0
READINESS_POLL_S: Final = 1.0
PROBE_TIMEOUT_S: Final = 3.0
PULL_TIMEOUT_S: Final = 1800.0
INSTALL_TIMEOUT_S: Final = 900.0


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def autostart_enabled() -> bool:
    """Whether this deployment has opted in. Off unless it says otherwise."""
    return _truthy(os.getenv(AUTOSTART_ENV))


def configured_models() -> tuple[str, ...]:
    """Every local model to warm, in order.

    Plural by requirement: the owner asked for "the local LLM and other local
    models". Blank entries are dropped so a trailing comma cannot produce a
    model named "".
    """
    raw = os.getenv(MODELS_ENV, "") or ""
    names = tuple(part.strip() for part in raw.split(",") if part.strip())
    return names or (DEFAULT_LOCAL_MODEL,)


def configured_tier() -> str:
    return (os.getenv(TIER_ENV, "") or "").strip() or DEFAULT_TIER


def tier_fits(tier: str, *, ram_gib: float, vram_gib: float) -> bool:
    """Whether `tier` can actually run on this much memory.

    An unknown tier never fits. A typo in `LOCAL_MODEL_TIER` must refuse rather
    than fall through to "sure" — the failure it would otherwise buy is the box
    swapping to a standstill while it holds open positions.
    """
    for name, min_ram, min_vram in TIERS:
        if name != tier:
            continue
        if min_vram and vram_gib >= min_vram:
            return True
        return bool(min_ram) and ram_gib >= min_ram
    logger.error(
        "local model: unknown tier %r; expected one of %s — refusing to start anything",
        tier,
        [name for name, _, _ in TIERS],
    )
    return False


def best_tier(ram_gib: float, vram_gib: float) -> str | None:
    """The largest tier these resources support, or None when none do."""
    for name, _, _ in TIERS:
        if tier_fits(name, ram_gib=ram_gib, vram_gib=vram_gib):
            return name
    return None


#: Where the per-platform installers live. One script per platform, so the
#: platform specifics stay somewhere a person can read them, and this module
#: only has to choose between them — which is the part worth unit-testing.
_SCRIPTS_DIR: Final = Path(__file__).resolve().parent.parent / "scripts"


def auto_install_enabled() -> bool:
    return _truthy(os.getenv(AUTO_INSTALL_ENV))


def ollama_present() -> bool:
    """Whether the binary is on PATH. The only honest test of "installed"."""
    return shutil.which("ollama") is not None


def install_command(system: str | None = None) -> list[str] | None:
    """How to install Ollama here, or None when this platform is not covered.

    None rather than a best guess: inventing an install command for an unknown
    operating system means running an unknown command as whatever user the
    deploy runs as.
    """
    name = (system or platform.system()).strip().lower()
    if name == "windows":
        return [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_SCRIPTS_DIR / "install_ollama.ps1"),
        ]
    if name in {"linux", "darwin"}:
        return ["bash", str(_SCRIPTS_DIR / "install_ollama.sh")]
    logger.error("local model: no Ollama installer for platform %r", name)
    return None


def _default_install_run(command: list[str]) -> None:
    subprocess.run(command, check=True, timeout=INSTALL_TIMEOUT_S)  # nosec B603 - argv from install_command, no shell


def ensure_installed(
    *,
    present: Callable[[], bool] = ollama_present,
    run: Callable[[list[str]], None] = _default_install_run,
) -> tuple[bool, str]:
    """Install Ollama if it is missing. (succeeded, detail).

    The install is proved by looking again, never by the installer exiting
    zero. An installer that returns 0 and installs nothing is precisely the
    "success reported for work that did not happen" shape this codebase has
    produced repeatedly, and it is a shape a package manager can genuinely
    produce — a winget source that resolves nothing still exits clean.
    """
    if present():
        return True, "already_installed"

    command = install_command()
    if command is None:
        return False, f"unsupported_platform: {platform.system()}"

    logger.info("local model: installing Ollama via %s", " ".join(command))
    try:
        run(command)
    except Exception as exc:
        logger.error("local model: Ollama install failed (%s)", exc)
        return False, f"install_failed: {exc}"

    if not present():
        return False, "still_absent: the installer finished but ollama is not on PATH"
    return True, "installed"


# ── measuring the machine ────────────────────────────────────────────────────


def total_ram_gib() -> float:
    """Total RAM in GiB, from /proc/meminfo with a sysconf fallback.

    Both failures are reported rather than swallowed: this number decides which
    model tier may run, so silently returning 0.0 would refuse every tier on a
    machine that could run one — a wrong answer dressed as a measurement.
    """
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024 * 1024)
    except OSError as exc:
        logger.warning("local model: /proc/meminfo unreadable (%s); trying sysconf", exc)

    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024**3)
    except (ValueError, OSError, AttributeError) as exc:
        logger.error("local model: could not measure RAM (%s); reporting 0", exc)
        return 0.0


def total_vram_gib() -> float:
    """Sum of GPU memory via nvidia-smi. Absent GPU tooling means 0, not unknown."""
    if not shutil.which("nvidia-smi"):
        return 0.0
    try:
        out = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("local model: nvidia-smi failed (%s); reporting 0 VRAM", exc)
        return 0.0
    total = 0.0
    for line in out.splitlines():
        try:
            total += float(line.strip()) / 1024
        except ValueError:
            continue
    return total


def measure_capacity() -> tuple[float, float]:
    return total_ram_gib(), total_vram_gib()


# ── the real external effects, injected as defaults ──────────────────────────


def _default_probe() -> bool:
    """True only when something answers Ollama's tag listing.

    This is the measurement that replaces `is_credentialed("ollama")` for the
    question "can the local leg answer".

    The request is made by `ai/gateway`'s OllamaAdapter rather than by an httpx
    call here, for a reason `tests/unit/test_no_model_call_bypasses_the_gateway.py`
    enforces and which this module tripped on its first run: every request to a
    model endpoint goes through the gateway, so there is one place that knows
    how to reach a provider and one place that can be audited. The adapter
    already owns a real probe — its own docstring notes that the health check it
    replaced answered `not_performed`, which is the same defect this module
    exists to remove one layer up.
    """
    from ai.gateway.adapters import OllamaAdapter

    reachable, _detail = OllamaAdapter().probe(timeout_s=PROBE_TIMEOUT_S)
    return bool(reachable)


def _default_launch() -> None:
    """Start `ollama serve` detached, or say plainly that it cannot be started."""
    binary = shutil.which("ollama")
    if not binary:
        raise OSError("ollama is not installed or not on PATH")
    subprocess.Popen(  # nosec B603 - fixed argv from shutil.which, no shell
        [binary, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # Its own session, so a signal sent to the API process group does not
        # kill the inference server out from under an in-flight request, and a
        # server left running is reused rather than duplicated on next boot.
        start_new_session=True,
    )


def _default_pull(model: str) -> None:
    binary = shutil.which("ollama")
    if not binary:
        raise OSError("ollama is not installed or not on PATH")
    result = subprocess.run(  # nosec B603 - fixed argv from shutil.which, no shell
        [binary, "pull", model],
        capture_output=True,
        text=True,
        timeout=PULL_TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ollama pull {model} exited {result.returncode}: {result.stderr.strip()[:200]}")


# ── status ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LocalModelStatus:
    """What actually happened, not what was attempted.

    `started` is set from the result of the work. `refusal` names why not, so a
    deployment that expected a local model and did not get one can find out from
    the status rather than from an inference failure hours later.
    """

    started: bool = False
    refusal: str | None = None
    tier: str = ""
    ram_gib: float = 0.0
    vram_gib: float = 0.0
    models_ready: tuple[str, ...] = ()
    models_failed: tuple[str, ...] = ()
    server_was_already_running: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "started": self.started,
            "refusal": self.refusal,
            "tier": self.tier,
            "ram_gib": round(self.ram_gib, 1),
            "vram_gib": round(self.vram_gib, 1),
            "models_ready": list(self.models_ready),
            "models_failed": list(self.models_failed),
            "server_was_already_running": self.server_was_already_running,
        }


class LocalModelRuntime:
    """Brings the local inference server and its models up at app startup."""

    def __init__(
        self,
        *,
        models: Iterable[str] | None = None,
        tier: str | None = None,
        capacity: Callable[[], tuple[float, float]] = measure_capacity,
        probe: Callable[[], bool] = _default_probe,
        launch: Callable[[], None] = _default_launch,
        pull: Callable[[str], None] = _default_pull,
        present: Callable[[], bool] = ollama_present,
        install_run: Callable[[list[str]], None] = _default_install_run,
        readiness_timeout_s: float = READINESS_TIMEOUT_S,
        poll_interval_s: float = READINESS_POLL_S,
    ) -> None:
        self._models = tuple(models) if models is not None else None
        self._tier = tier
        self._capacity = capacity
        self._probe = probe
        self._launch = launch
        self._pull = pull
        self._present = present
        self._install_run = install_run
        self._readiness_timeout_s = readiness_timeout_s
        self._poll_interval_s = poll_interval_s
        self._status = LocalModelStatus()

    # -- read-only surface ---------------------------------------------------

    @property
    def models(self) -> tuple[str, ...]:
        return self._models if self._models is not None else configured_models()

    @property
    def tier(self) -> str:
        return self._tier or configured_tier()

    def status(self) -> LocalModelStatus:
        return self._status

    def is_ready(self) -> bool:
        """Whether the local leg can actually answer, measured now.

        A probe that raises is evidence of no server, not of an unknown state —
        so it is False, and it is logged, because a control that swallows its
        own evidence is the defect this module was written under.
        """
        try:
            return bool(self._probe())
        except Exception as exc:
            logger.warning("local model: readiness probe failed (%s); treating as not ready", exc)
            return False

    # -- startup -------------------------------------------------------------

    async def start(self) -> LocalModelStatus:
        """Bring the server and models up. Never raises; always returns a status."""
        try:
            self._status = await self._start()
        except Exception as exc:  # a startup component must not take the app down
            logger.error("local model: startup failed unexpectedly (%s); local inference is off", exc)
            self._status = LocalModelStatus(refusal=f"unexpected_error: {exc}")
        return self._status

    async def _start(self) -> LocalModelStatus:
        if not autostart_enabled():
            logger.info(
                "local model: autostart disabled (set %s=true to run models on this machine)",
                AUTOSTART_ENV,
            )
            return LocalModelStatus(refusal="autostart_disabled")

        tier = self.tier
        ram, vram = await asyncio.to_thread(self._capacity)
        if not tier_fits(tier, ram_gib=ram, vram_gib=vram):
            fits = best_tier(ram, vram)
            logger.error(
                "local model: refusing to start tier %s — this machine has %.1f GiB RAM and "
                "%.1f GiB VRAM. An oversized model does not degrade, it swaps the box to a "
                "standstill, and this box also executes orders. Largest viable tier here: %s. "
                "Run scripts/vps_capability_report.py and set %s.",
                tier,
                ram,
                vram,
                fits or "none",
                TIER_ENV,
            )
            return LocalModelStatus(refusal=f"tier_does_not_fit: {tier}", tier=tier, ram_gib=ram, vram_gib=vram)

        already_running = self.is_ready()
        if not already_running:
            if not self._present():
                if auto_install_enabled():
                    installed, detail = await asyncio.to_thread(
                        ensure_installed, present=self._present, run=self._install_run
                    )
                    if not installed:
                        logger.error(
                            "local model: Ollama is not installed and the automatic install "
                            "failed (%s). Run scripts/install_ollama.sh (Linux/macOS) or "
                            "scripts/install_ollama.ps1 (Windows).",
                            detail,
                        )
                        return LocalModelStatus(
                            refusal=f"install_ollama: {detail}", tier=tier, ram_gib=ram, vram_gib=vram
                        )
                else:
                    # A refusal an operator can act on. "not installed" is a dead
                    # end; naming the script is a next step. Installing without
                    # being asked is not the answer — LOCAL_MODEL_AUTO_INSTALL is
                    # how a deployment opts into that.
                    logger.error(
                        "local model: Ollama is not installed. Run scripts/install_ollama.sh "
                        "(Linux/macOS) or scripts/install_ollama.ps1 (Windows), or set %s=true "
                        "to let the runtime install it.",
                        AUTO_INSTALL_ENV,
                    )
                    return LocalModelStatus(
                        refusal="install_ollama: not installed and auto-install is off",
                        tier=tier,
                        ram_gib=ram,
                        vram_gib=vram,
                    )
            try:
                await asyncio.to_thread(self._launch)
            except Exception as exc:
                logger.error(
                    "local model: could not start the inference server (%s); the hosted chain is "
                    "unaffected, but the local leg cannot answer",
                    exc,
                )
                return LocalModelStatus(refusal=f"server_not_started: {exc}", tier=tier, ram_gib=ram, vram_gib=vram)
            if not await self._await_ready():
                logger.error(
                    "local model: the inference server did not answer within %.0fs of being "
                    "started; the local leg cannot answer",
                    self._readiness_timeout_s,
                )
                return LocalModelStatus(refusal="server_not_ready", tier=tier, ram_gib=ram, vram_gib=vram)

        ready: list[str] = []
        failed: list[str] = []
        for model in self.models:
            try:
                await asyncio.to_thread(self._pull, model)
            except Exception as exc:
                # One bad model name must not cost the others. Logged at ERROR
                # and named in the status, so it is findable without the log.
                logger.error("local model: could not warm %r (%s); continuing with the rest", model, exc)
                failed.append(model)
            else:
                ready.append(model)

        status = LocalModelStatus(
            started=bool(ready),
            refusal=None if ready else "no_model_warmed",
            tier=tier,
            ram_gib=ram,
            vram_gib=vram,
            models_ready=tuple(ready),
            models_failed=tuple(failed),
            server_was_already_running=already_running,
        )
        logger.info("local model: %s", status.as_dict())
        return status

    async def _await_ready(self) -> bool:
        deadline = asyncio.get_running_loop().time() + self._readiness_timeout_s
        while asyncio.get_running_loop().time() < deadline:
            if self.is_ready():
                return True
            await asyncio.sleep(self._poll_interval_s)
        return self.is_ready()


_RUNTIME: LocalModelRuntime | None = None


def get_local_model_runtime() -> LocalModelRuntime:
    """The process-wide runtime, so status has one answer rather than several."""
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = LocalModelRuntime()
    return _RUNTIME


def reset_local_model_runtime() -> None:
    """Drop the singleton. For tests only."""
    global _RUNTIME
    _RUNTIME = None


__all__ = [
    "AUTOSTART_ENV",
    "AUTO_INSTALL_ENV",
    "DEFAULT_LOCAL_MODEL",
    "DEFAULT_TIER",
    "MODELS_ENV",
    "TIERS",
    "TIER_ENV",
    "LocalModelRuntime",
    "LocalModelStatus",
    "auto_install_enabled",
    "autostart_enabled",
    "ensure_installed",
    "install_command",
    "ollama_present",
    "best_tier",
    "configured_models",
    "configured_tier",
    "get_local_model_runtime",
    "measure_capacity",
    "reset_local_model_runtime",
    "tier_fits",
    "total_ram_gib",
    "total_vram_gib",
]

if __name__ == "__main__":  # pragma: no cover - convenience for a VPS operator
    ram, vram = measure_capacity()
    print(f"RAM {ram:.1f} GiB   VRAM {vram:.1f} GiB   largest viable tier: {best_tier(ram, vram)}")
    sys.exit(0)
