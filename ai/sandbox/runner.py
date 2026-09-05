# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Where agent-authored code runs without a route to a real venue.

What this contains
------------------
* A **separate process**, so a crash or a runaway cannot take the API down.
* A **scrubbed environment**. The child inherits an explicit allowlist of
  variables and nothing else. No broker credentials, no model API keys, no JWT
  secret, no database password. This is the boundary that makes "no route to a
  real venue" true: an order cannot be placed without credentials, whatever the
  code does.
* A **disposable working directory**, removed afterwards, so the repository is
  not writable through a relative path.
* **Resource limits** (CPU seconds, address space, file descriptors, no core
  dump) applied in the child before the code is reached.
* A **wall-clock timeout** with a kill, because CPU limits do not stop a
  process that is blocked on I/O.
* A **socket block** installed before the code runs, when ``net=False``.
* The existing static screen from ``security/ai_repair_sandbox`` as a
  pre-filter, so banned imports and syntax errors are refused before a process
  is spawned at all.

What this does NOT contain
--------------------------
Stated plainly, because a sandbox that overstates its isolation is worse than
none -- work gets trusted to it.

* **It is not a kernel-level jail.** There is no namespace, no seccomp filter
  and no container. Code running here is confined by Python-level and rlimit
  measures that determined native code could subvert.
* **The socket block is defence in depth, not a boundary.** It replaces
  ``socket.socket`` in the child interpreter; code that reaches the syscall by
  another route is not stopped by it. The credential scrub is what makes venue
  access impossible, and that is the control to rely on.
* **The filesystem is not read-confined.** The child cannot easily write to the
  repository because its working directory is elsewhere, but it can still read
  what the user running it can read.

Use it for agent-authored strategies and candidate repairs. Do not use it as
the only barrier against hostile native code.
"""

from __future__ import annotations

import logging
import os
import resource
import subprocess  # nosec B404 - fixed argv, no shell, scrubbed env; see module docstring
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 10.0
DEFAULT_CPU_SECONDS = 5
DEFAULT_ADDRESS_SPACE_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_FDS = 64

#: The only variables the child inherits. Everything else -- every credential,
#: key, token and password in the parent's environment -- is dropped.
_ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "TZ")

#: Installed in the child before the candidate code runs.
_PREAMBLE_NO_NET = """
import socket as _socket


class _SandboxBlockedSocket(_socket.socket):
    def __init__(self, *a, **kw):
        raise OSError("sandbox: network access is disabled for this run")


def _sandbox_blocked(*a, **kw):
    raise OSError("sandbox: network access is disabled for this run")


_socket.socket = _SandboxBlockedSocket
_socket.create_connection = _sandbox_blocked
_socket.socketpair = _sandbox_blocked
del _SandboxBlockedSocket, _sandbox_blocked
"""


@dataclass(frozen=True)
class SandboxResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    duration_ms: float = 0.0


def _limits() -> None:
    """Applied in the child, before exec. Never call this in the parent."""
    resource.setrlimit(resource.RLIMIT_CPU, (DEFAULT_CPU_SECONDS, DEFAULT_CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (DEFAULT_ADDRESS_SPACE_BYTES, DEFAULT_ADDRESS_SPACE_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (DEFAULT_MAX_FDS, DEFAULT_MAX_FDS))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setsid()


def run(
    code: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    net: bool = False,
    extra_env: dict[str, str] | None = None,
    prefilter: bool = True,
) -> SandboxResult:
    """Execute `code` in a contained child process.

    `prefilter=False` skips the static screen and exercises the containment
    layer alone. The containment guarantees must hold WITHOUT the screen -- that
    is what makes them defence in depth rather than a single denylist -- so the
    tests prove them with the screen off. Production callers leave it on.
    """
    started = time.perf_counter()

    # Pre-filter first: refuse before spawning anything at all.
    if prefilter:
        try:
            from security.ai_repair_sandbox import validate_repair_source

            screened = validate_repair_source(code)
            if not screened.accepted:
                return SandboxResult(
                    ok=False,
                    stderr="static screen refused the candidate",
                    reason_codes=tuple(screened.reason_codes),
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
        except ImportError:  # the pre-filter is optional, the containment is not
            logger.warning("ai.sandbox: static pre-filter unavailable; continuing with containment only")

    env = {name: os.environ[name] for name in _ENV_ALLOWLIST if name in os.environ}
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(extra_env or {})

    body = code if net else _PREAMBLE_NO_NET + "\n" + code

    with tempfile.TemporaryDirectory(prefix="hopefx-sandbox-") as workdir:
        script = Path(workdir) / "candidate.py"
        script.write_text(body, encoding="utf-8")
        try:
            completed = subprocess.run(  # nosec B603 - fixed argv, no shell
                [sys.executable, "-I", "-B", str(script)],
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
                preexec_fn=_limits,
            )
        except subprocess.TimeoutExpired as exc:
            return SandboxResult(
                ok=False,
                stdout=_text(exc.stdout),
                stderr="sandbox: wall-clock timeout",
                reason_codes=("timeout",),
                duration_ms=(time.perf_counter() - started) * 1000,
            )

    duration_ms = (time.perf_counter() - started) * 1000
    if completed.returncode != 0:
        return SandboxResult(
            ok=False,
            stdout=completed.stdout,
            stderr=completed.stderr,
            reason_codes=("nonzero_exit",),
            duration_ms=duration_ms,
        )
    return SandboxResult(ok=True, stdout=completed.stdout, stderr=completed.stderr, duration_ms=duration_ms)


def _text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


__all__ = ["DEFAULT_TIMEOUT_S", "SandboxResult", "run"]
