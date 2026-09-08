# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Gate L is the gate that stops the platform trading real money by accident.

It had **no test at all** — one of eleven CI gates in that position. Rule 1 says
a control with no evidence it can return a negative result is treated as absent,
which made the most safety-critical gate in the repository absent by its own
standard.

These tests are the evidence. Each one reproduces an incident gate L claims to
prevent — live trading enabled by default, a broker switched off paper, drift or
staleness blocking disabled, WebSocket auth or Redis TLS turned off — and asserts
the gate refuses.

**The injections run against a copied tree, never the real files.** `gate_l`
derives `REPO_ROOT` from its own location (`parents[2]`), so copying the gate into
`<tmp>/scripts/ci/` alongside copies of the three files it reads gives a complete,
disposable repository. The gate under test is the real file, byte for byte; only
the tree it inspects is a copy. Mutating the working tree to test a safety gate
is how a test leaves live trading enabled when it fails half way through.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 — runs the gate under test, fixed argument list
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "ci" / "gate_l_safety_invariants.py"

#: Everything gate L reads. Derived from the gate itself rather than guessed —
#: if it grows a rule over a new file, the fixture stops being representative and
#: `test_the_fixture_covers_every_file_the_gate_reads` says so.
_FIXTURE_FILES = (
    Path(".env.example"),
    Path("config") / "feature_flags.py",
    Path("ml") / "inference_engine.py",
)


def _mirror(tmp_path: Path) -> Path:
    """A disposable repository the gate will accept as its own root."""
    root = tmp_path / "repo"
    (root / "scripts" / "ci").mkdir(parents=True)
    shutil.copy2(GATE, root / "scripts" / "ci" / GATE.name)
    for rel in _FIXTURE_FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, root / rel)
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — fixed argument list, no shell
        [sys.executable, str(root / "scripts" / "ci" / GATE.name)],
        capture_output=True,
        text=True,
        check=False,
    )


def _edit(root: Path, rel: Path, old: str, new: str) -> None:
    path = root / rel
    text = path.read_text(encoding="utf-8")
    assert old in text, f"injection target {old!r} not present in {rel} — the injection would be a no-op"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


class TestTheHarnessItself:
    """A gate that fails on an unmodified mirror would make every test below
    pass for the wrong reason."""

    def test_an_unmodified_mirror_passes(self, tmp_path: Path) -> None:
        result = _run(_mirror(tmp_path))
        assert result.returncode == 0, f"the mirror is not faithful:\n{result.stdout}\n{result.stderr}"

    def test_the_fixture_covers_every_file_the_gate_reads(self) -> None:
        # If a rule is added over a fourth file, the mirror silently stops
        # representing the repository and the injections below get weaker
        # without anyone noticing.
        import re

        referenced = set(re.findall(r'REPO_ROOT / "([^"]+)"(?: / "([^"]+)")?', GATE.read_text(encoding="utf-8")))
        expected = {(str(p.parts[0]), str(p.parts[1]) if len(p.parts) > 1 else "") for p in _FIXTURE_FILES}
        assert referenced == expected, f"gate L now reads {referenced}; the fixture mirrors {expected}"


class TestTheGateRefusesEveryIncidentItClaimsToPrevent:
    """Seven injections, seven refusals. Each is a real incident shape, not a
    syntactic mutation: this is the difference between evidence the gate *can*
    fail and evidence it fails *on the thing it exists for*."""

    def test_a_live_broker_in_the_template_is_refused(self, tmp_path: Path) -> None:
        root = _mirror(tmp_path)
        _edit(root, Path(".env.example"), "BROKER_TYPE=paper", "BROKER_TYPE=oanda")
        result = _run(root)
        assert result.returncode != 0, "a live broker default did not fail gate L"
        assert "BROKER_TYPE" in result.stdout + result.stderr

    def test_live_trading_enabled_in_the_template_is_refused(self, tmp_path: Path) -> None:
        root = _mirror(tmp_path)
        _edit(root, Path(".env.example"), "FEATURE_LIVE_TRADING=false", "FEATURE_LIVE_TRADING=true")
        assert _run(root).returncode != 0, "live trading enabled by default did not fail gate L"

    def test_live_trading_defaulting_true_in_code_is_refused(self, tmp_path: Path) -> None:
        # The two-key lock: the template is one key, the feature-flag descriptor
        # is the other. Both must fail the gate independently.
        root = _mirror(tmp_path)
        _edit(root, Path("config") / "feature_flags.py", "default=False", "default=True")
        assert _run(root).returncode != 0, "a live-trading default of True in code did not fail gate L"

    def test_drift_blocking_disabled_is_refused(self, tmp_path: Path) -> None:
        root = _mirror(tmp_path)
        _edit(root, Path(".env.example"), "DRIFT_BLOCK=true", "DRIFT_BLOCK=false")
        assert _run(root).returncode != 0, "disabled drift blocking did not fail gate L"

    def test_stale_model_blocking_disabled_is_refused(self, tmp_path: Path) -> None:
        root = _mirror(tmp_path)
        _edit(
            root,
            Path("ml") / "inference_engine.py",
            'os.getenv("STALE_MODEL_BLOCK", "true")',
            'os.getenv("STALE_MODEL_BLOCK", "false")',
        )
        assert _run(root).returncode != 0, "disabled stale-model blocking did not fail gate L"

    def test_websocket_auth_disabled_is_refused(self, tmp_path: Path) -> None:
        root = _mirror(tmp_path)
        _edit(root, Path(".env.example"), "WS_AUTH_REQUIRED=true", "WS_AUTH_REQUIRED=false")
        assert _run(root).returncode != 0, "disabled WebSocket auth did not fail gate L"

    def test_redis_tls_disabled_is_refused(self, tmp_path: Path) -> None:
        root = _mirror(tmp_path)
        _edit(root, Path(".env.example"), "REDIS_FORCE_TLS=true", "REDIS_FORCE_TLS=false")
        assert _run(root).returncode != 0, "disabled Redis TLS did not fail gate L"


class TestAMissingFileIsRefusedRatherThanSkipped:
    """Rule 3. A rule whose file has been deleted or renamed must fail closed —
    a gate that quietly skips rules it cannot evaluate reports a pass it did not
    earn, and deleting a file is a plausible way to defeat it."""

    @pytest.mark.parametrize("missing", [p for p in _FIXTURE_FILES])
    def test_deleting_a_file_the_gate_reads_fails_the_gate(self, tmp_path: Path, missing: Path) -> None:
        root = _mirror(tmp_path)
        (root / missing).unlink()
        assert _run(root).returncode != 0, f"gate L passed with {missing} missing"
