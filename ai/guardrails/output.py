# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Output validation between a model and any action it might cause.

Generalised from `news/geopolitical_llm.py` (audit F261), which established the
two rules that matter:

**Validate, never coerce.** A response the model did not produce in the
requested shape is a FAILED extraction, and the caller's fallback to a
deterministic answer is the safe result -- not a number squeezed out of whatever
came back. `"7"` must not quietly become `7`, because a model that returned a
string when asked for a number has not answered the question, and treating it as
though it had is how an unreliable reading reaches a decision.

**An uncorroborated claim gets a ceiling.** A model may not on its own reach a
tier at which the platform acts. When a deterministic source independently
agrees, the ceiling rises to meet it -- so sensitivity is not lost, and the cap
binds only when nothing corroborates.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

#: Credential SHAPES, checked against everything a model says on the way out.
#:
#: Nothing screened model output at all: this module validated the shape of a
#: response rigorously and never looked at its content, so a model that had been
#: shown a credential -- or reconstructed one from context -- could hand it back
#: to an operator, into a log line, or into the department memory layer.
#:
#: These are patterns, not a scanner: `detect-secrets` lives only in the
#: pre-commit hook's own virtualenv, is not a runtime dependency, and is built
#: for sweeping files rather than for the hot path of every model call. The
#: shapes below are the ones that matter for this deployment.
#:
#: Each entry is (label, pattern). The label is what a refusal reports. The
#: MATCH IS NEVER REPORTED -- see `_refuse`.
_CREDENTIAL_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic api key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai api key", re.compile(r"\bsk-(?!ant-)[A-Za-z0-9_\-]{20,}")),
    ("aws access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z\-]{20,}")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("json web token", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    # A connection string carrying its own password. Excludes the empty-password
    # and token-placeholder forms so `redis://localhost:6379` stays fine.
    ("credential in a url", re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s:/@]{3,}@[^\s/]+")),
)

#: Values this deployment knows are secret, registered at startup.
#:
#: Patterns cannot cover a secret with no distinctive shape -- this platform's
#: own JWT signing key, a broker password, the system prompt. Registering the
#: live values is what makes leakage of those detectable at all, and it is the
#: only mechanism here that can catch system-prompt echo.
#:
#: Held as {label: value}. The value is never logged, never included in a
#: refusal, and never leaves this module.
_KNOWN: dict[str, str] = {}

#: Below this length a registered value matches ordinary prose and would refuse
#: almost every answer. A short secret is a problem to fix at the source, not
#: something to make the output guardrail useless over.
_MIN_KNOWN_LEN = 8


class GuardrailViolation(RuntimeError):
    """Model output failed validation. Never fall back to another vendor for this.

    A guardrail rejection is an ANSWER, not a transport failure: retrying it on
    a second provider does not get a better result, it defeats the guardrail.
    `ai.gateway.chain.should_fall_through` encodes that.
    """


def register_known_secret(label: str, value: str) -> None:
    """Teach the scanner one of this deployment's real credentials.

    Called at startup with values already in the process (the JWT signing
    secret, broker passwords). Anything shorter than `_MIN_KNOWN_LEN` is
    ignored, because a short value matches ordinary prose and would turn the
    guardrail into a refusal of everything.
    """
    if value and len(value) >= _MIN_KNOWN_LEN:
        _KNOWN[label] = value


def reset_known_secrets() -> None:
    _KNOWN.clear()


def known_secret_count() -> int:
    """For the health surface: how many live values are being watched for."""
    return len(_KNOWN)


def _refuse(label: str) -> None:
    """Raise naming only WHAT leaked, never the value.

    A scanner that quotes its finding copies the secret out of a model response
    and into an exception string, a stack trace and a log aggregator -- which is
    strictly worse than not having scanned. The label is enough to act on.
    """
    raise GuardrailViolation(
        f"model output withheld: it contains something shaped like a {label}. "
        f"The value is deliberately not reproduced here."
    )


def scan_output(raw: str) -> None:
    """Refuse model output that carries a credential. Returns None or raises.

    Deliberately a separate stage from `validate_output`: content screening has
    to apply to free-text answers too, not only to the structured path.
    """
    text = raw or ""
    if not text:
        return

    for label, value in _KNOWN.items():
        if value in text:
            _refuse(f"registered credential ({label})")

    for label, pattern in _CREDENTIAL_SHAPES:
        if pattern.search(text):
            _refuse(label)


#: Characters held back from release while a stream is still arriving.
#:
#: Sized against the SHORTEST complete credential the shapes above can match —
#: an AWS access key id at 20 characters — so that no shape can have a usable
#: prefix released before the buffer scan sees the whole of it. 64 also covers
#: the one multi-word shape, `-----BEGIN ENCRYPTED PRIVATE KEY-----` (37).
#:
#: It is a FLOOR, not the whole rule: `register_known_secret` accepts a value of
#: any length, so `StreamScanner` widens the holdback to cover the longest
#: registered value. A fixed constant alone would release all but the last 64
#: characters of a registered system prompt, one chunk at a time, and refuse
#: only once the last character arrived — by which point it is on the screen.
_STREAM_HOLDBACK = 64


class StreamScanner:
    """Screen model output that arrives in pieces, releasing what is safe.

    `scan_output` works because the whole answer is in hand when it runs.
    Streaming breaks that: text reaches the screen as it arrives, so a
    credential that is only complete at the end has already been rendered, and
    there is no taking it back. A streaming path that skipped this would be the
    output guardrail existing and not running — which is the defect shape this
    repository has the most of.

    Two rules, and the first is the one that makes it sound:

    1. **Only a prefix of a buffer that scanned clean is ever released.** The
       whole buffer is re-scanned on every chunk. `re.search` finds substrings,
       so a prefix of a string with no match has no match: releasing prefixes
       of clean buffers cannot release a *complete* credential. This holds for
       shapes of unbounded length, which is why the buffer is rescanned whole
       rather than through a sliding window — a window is faster and only
       catches credentials shorter than itself.

    2. **A tail is held back**, so a *partial* credential is not released
       either. Half an API key is still a leak.

    Rescanning the whole buffer is O(n²) in the number of chunks. Measured at
    roughly 18KB of answer it is milliseconds; a security control is the wrong
    place to trade correctness for a constant factor at this scale.

    Usage — `feed` returns the text safe to show, `finish` releases the tail:

        scanner = StreamScanner()
        for chunk in transport:
            emit(scanner.feed(chunk))     # raises GuardrailViolation
        emit(scanner.finish())
        cache(scanner.text)               # the whole answer, for cache/audit
    """

    def __init__(self) -> None:
        self._buf = ""
        self._released = 0
        self._finished = False

    @property
    def text(self) -> str:
        """Everything received so far. What the cache and the audit record —
        neither wants the answer in the pieces it happened to arrive in."""
        return self._buf

    def _holdback(self) -> int:
        # Recomputed per chunk: a registered value can be added at any time, and
        # reading `_KNOWN` here is cheaper than being wrong about it.
        longest_known = max((len(v) for v in _KNOWN.values()), default=0)
        return max(_STREAM_HOLDBACK, longest_known)

    def feed(self, chunk: str) -> str:
        """Add `chunk`; return the text now safe to show. May raise.

        Raises `GuardrailViolation` exactly as `scan_output` does, and for the
        same reason: a rejection is an ANSWER, not a transport failure, so the
        caller must not retry it on another vendor.
        """
        if not chunk:
            return ""
        self._buf += chunk
        scan_output(self._buf)
        cut = max(0, len(self._buf) - self._holdback())
        if cut <= self._released:
            return ""
        out = self._buf[self._released : cut]
        self._released = cut
        return out

    def finish(self) -> str:
        """Release the held tail once the stream has genuinely ended.

        Scans once more so a short answer — one that never exceeded the
        holdback and so was never released — is still screened. Idempotent:
        a second call returns nothing rather than repeating the tail.
        """
        if self._finished:
            return ""
        self._finished = True
        scan_output(self._buf)
        out = self._buf[self._released :]
        self._released = len(self._buf)
        return out


def validate_output(
    raw: str,
    *,
    required: dict[str, tuple[type, ...]] | None = None,
    ranges: dict[str, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """Parse `raw` into a dict, or raise GuardrailViolation.

    `required` maps a field name to the types it may be. `ranges` maps a numeric
    field to its inclusive bounds. Both are checked without coercion.

    Content screening runs first, so the structured path is not a way around
    `scan_output`. A credential inside a JSON field is still a credential.
    """
    scan_output(raw)
    text = _FENCE.sub("", (raw or "").strip()).strip()
    match = _OBJECT.search(text)
    if not match:
        raise GuardrailViolation("no JSON object in model output")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise GuardrailViolation(f"model output is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise GuardrailViolation("model output is not a JSON object")

    for field, types in (required or {}).items():
        if field not in data:
            raise GuardrailViolation(f"model output missing required field {field!r}")
        value = data[field]
        # bool is a subclass of int in Python, so `True` would satisfy a numeric
        # check and read as severity 1. It is not a number the model chose.
        if isinstance(value, bool) and bool not in types:
            raise GuardrailViolation(f"field {field!r} is a boolean, not {types}")
        if not isinstance(value, types):
            raise GuardrailViolation(
                f"field {field!r} is {type(value).__name__}, not one of {[t.__name__ for t in types]} -- not coercing"
            )

    for field, (low, high) in (ranges or {}).items():
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, (int, float)) or not (low <= float(value) <= high):
            raise GuardrailViolation(f"field {field!r} out of range [{low}, {high}]: {value!r}")

    return data


def bounded_severity(*, model_value: float, corroborated_value: float, ceiling: float) -> tuple[float, bool]:
    """Cap an uncorroborated model claim. Returns (value, was_capped).

    The ceiling is the last tier at which the platform takes NO action. Above it
    a deterministic source must independently agree -- and when it does, the
    ceiling rises to that value, so a real event still acts at full strength.
    A corroborated value is never lowered.
    """
    effective_ceiling = max(ceiling, corroborated_value)
    if model_value > effective_ceiling:
        return effective_ceiling, True
    return max(model_value, corroborated_value), False


__all__ = [
    "GuardrailViolation",
    "StreamScanner",
    "bounded_severity",
    "known_secret_count",
    "register_known_secret",
    "reset_known_secrets",
    "scan_output",
    "validate_output",
]
