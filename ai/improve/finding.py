# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""One thing the walker noticed, and the evidence for it.

The capability registry's discipline, applied to code review: a claim that
cannot point at what it saw is not a claim, it is an opinion. `resolves()` opens
the file and checks the line is really there, the same way
`ai/hub/capabilities.py:verify()` resolves an evidence locator rather than
trusting it.

**A snippet is untrusted text.** The walker reads repository files, and a
comment, a docstring or a vendored dependency can carry an instruction. Anything
from a file that goes on to reach a model goes through
`ai/guardrails/input.py:fence` first — quarantined and labelled, never deleted,
because a finding whose evidence was silently edited is worth less than none.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Final, Literal

Severity = Literal["high", "medium", "low"]

_ROOT: Final[pathlib.Path] = pathlib.Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Finding:
    """A file, a line, a claim, and whether anything may be proposed about it."""

    check: str
    #: Repository-relative, POSIX separators.
    path: str
    #: 1-based, like every editor and every traceback.
    line: int
    claim: str
    snippet: str = ""
    severity: Severity = "medium"
    #: False when the path is in `ai/vault/protected.py`'s floor. The walker
    #: still reads protected files — noticing a problem in the risk manager is
    #: the point — but nothing downstream may turn this into a patch.
    proposable: bool = True

    def __post_init__(self) -> None:
        if not self.check.strip():
            raise ValueError("a finding names the check that produced it")
        if not self.path.strip():
            raise ValueError("a finding names a file")
        if self.line < 1:
            raise ValueError(f"line numbers are 1-based; got {self.line}")
        if not self.claim.strip():
            raise ValueError("a finding states a claim; 'looks wrong' is not a finding and neither is nothing")

    @property
    def evidence(self) -> str:
        """`path:line`. Clickable, and resolvable."""
        return f"{self.path}:{self.line}"

    def resolves(self, root: pathlib.Path | None = None) -> bool:
        """Whether the file exists and really has that line."""
        base = root or _ROOT
        target = base / self.path
        try:
            if not target.is_file():
                return False
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return self.line <= len(text.splitlines())

    def as_prompt_data(self) -> str:
        """This finding's snippet, quarantined for inclusion in a prompt."""
        from ai.guardrails.input import fence

        return fence(self.snippet, kind="code")

    def as_dict(self) -> dict[str, object]:
        return {
            "check": self.check,
            "path": self.path,
            "line": self.line,
            "claim": self.claim,
            "severity": self.severity,
            "proposable": self.proposable,
            "evidence": self.evidence,
        }
