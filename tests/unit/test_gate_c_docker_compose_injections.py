# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Gate C — docker-compose.yml structural safety defaults.

Verifies PAPER_TRADING defaults to true, IS_FORCE_TLS and REDIS_FORCE_TLS
default to false, and alertmanager uses build: (so its envsubst entrypoint
actually runs) rather than image:. It had no test.

Two paths exist — `_check_yaml` (PyYAML present) and `_check_regex` (a
fallback). A fallback nobody exercises is exactly the shape this repository
keeps finding dead, so both are proven here: unit-level against the pure
functions for precision, and end-to-end against a real mutated copy of the
repository's actual docker-compose.yml (not a synthetic minimal one) so an
injection also proves the gate's anchors still match the real file's layout.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 — runs the gate under test, fixed argument list
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "ci" / "gate_c_docker_compose.py"


def _load_gate():
    """Import the gate module directly, for the pure-function-level checks."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("gate_c_docker_compose", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mirror(tmp_path: Path) -> Path:
    """A disposable repository holding the real gate and the real compose file."""
    root = tmp_path / "repo"
    (root / "scripts" / "ci").mkdir(parents=True)
    shutil.copy2(GATE, root / "scripts" / "ci" / GATE.name)
    shutil.copy2(REPO / "docker-compose.yml", root / "docker-compose.yml")
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — fixed argument list, no shell
        [sys.executable, str(root / "scripts" / "ci" / GATE.name)],
        capture_output=True,
        text=True,
        check=False,
        cwd=root,
    )


def _inject(root: Path, old: str, new: str) -> None:
    """Edit docker-compose.yml, and prove the edit actually landed."""
    path = root / "docker-compose.yml"
    before = path.read_text(encoding="utf-8")
    assert old in before, f"anchor {old!r} not found — the real compose file's layout changed"
    after = before.replace(old, new, 1)
    assert after != before, "injection did not apply — it would prove nothing"
    path.write_text(after, encoding="utf-8")


class TestTheMirrorIsFaithful:
    def test_an_untouched_mirror_passes(self, mirror: Path) -> None:
        result = _run(mirror)
        assert result.returncode == 0, result.stdout + result.stderr

    def test_the_gate_reports_something_when_the_file_is_missing(self, mirror: Path) -> None:
        (mirror / "docker-compose.yml").unlink()
        result = _run(mirror)
        assert result.returncode == 1
        assert "not found" in result.stdout


class TestItCatchesEachRealDefault:
    def test_paper_trading_defaulting_to_false_fails(self, mirror: Path) -> None:
        _inject(mirror, "PAPER_TRADING: ${PAPER_TRADING:-true}", "PAPER_TRADING: ${PAPER_TRADING:-false}")
        result = _run(mirror)
        assert result.returncode == 1
        assert "PAPER_TRADING" in result.stdout

    def test_is_force_tls_defaulting_to_true_fails(self, mirror: Path) -> None:
        _inject(mirror, "IS_FORCE_TLS: ${IS_FORCE_TLS:-false}", "IS_FORCE_TLS: ${IS_FORCE_TLS:-true}")
        result = _run(mirror)
        assert result.returncode == 1
        assert "IS_FORCE_TLS" in result.stdout

    def test_redis_force_tls_defaulting_to_true_fails(self, mirror: Path) -> None:
        _inject(mirror, "REDIS_FORCE_TLS: ${REDIS_FORCE_TLS:-false}", "REDIS_FORCE_TLS: ${REDIS_FORCE_TLS:-true}")
        result = _run(mirror)
        assert result.returncode == 1
        assert "REDIS_FORCE_TLS" in result.stdout

    def test_alertmanager_switched_to_image_without_build_fails(self, mirror: Path) -> None:
        _inject(
            mirror,
            "  alertmanager:\n    build:\n      context: ./monitoring/alertmanager\n      dockerfile: Dockerfile\n",
            "  alertmanager:\n    image: prom/alertmanager:latest\n",
        )
        result = _run(mirror)
        assert result.returncode == 1
        assert "alertmanager" in result.stdout


class TestTheYamlAndRegexPathsAgree:
    """A fallback path nobody exercises is exactly the shape this repository
    keeps finding dead. Both `_check_yaml` and `_check_regex` are called
    directly here, on the same inputs, so neither can silently diverge or
    rot unnoticed just because PyYAML happens to be installed in CI."""

    @pytest.fixture
    def gate(self):
        return _load_gate()

    @pytest.fixture
    def good_content(self) -> str:
        return (REPO / "docker-compose.yml").read_text(encoding="utf-8")

    def test_both_paths_pass_the_real_file(self, gate, good_content: str) -> None:
        assert gate._check_yaml(good_content) == []
        assert gate._check_regex(good_content) == []

    def test_both_paths_catch_paper_trading_false(self, gate, good_content: str) -> None:
        bad = good_content.replace("PAPER_TRADING: ${PAPER_TRADING:-true}", "PAPER_TRADING: ${PAPER_TRADING:-false}")
        assert bad != good_content
        assert gate._check_yaml(bad), "_check_yaml did not catch PAPER_TRADING defaulting to false"
        assert gate._check_regex(bad), "_check_regex did not catch PAPER_TRADING defaulting to false"

    def test_both_paths_catch_is_force_tls_true(self, gate, good_content: str) -> None:
        bad = good_content.replace("IS_FORCE_TLS: ${IS_FORCE_TLS:-false}", "IS_FORCE_TLS: ${IS_FORCE_TLS:-true}")
        assert bad != good_content
        assert gate._check_yaml(bad), "_check_yaml did not catch IS_FORCE_TLS defaulting to true"
        assert gate._check_regex(bad), "_check_regex did not catch IS_FORCE_TLS defaulting to true"

    def test_both_paths_catch_alertmanager_image_without_build(self, gate, good_content: str) -> None:
        bad = good_content.replace(
            "  alertmanager:\n    build:\n      context: ./monitoring/alertmanager\n      dockerfile: Dockerfile\n",
            "  alertmanager:\n    image: prom/alertmanager:latest\n",
        )
        assert bad != good_content
        assert gate._check_yaml(bad), "_check_yaml did not catch alertmanager using image: without build:"
        assert gate._check_regex(bad), "_check_regex did not catch alertmanager using image: without build:"

    def test_a_malformed_yaml_file_is_reported_not_crashed_on(self, gate) -> None:
        failures = gate._check_yaml("services:\n  broken: [unterminated\n")
        assert failures and "parse error" in failures[0]
