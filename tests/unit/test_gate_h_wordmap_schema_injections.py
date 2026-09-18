# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Gate H — WORDMAP.json.example schema validation.

`WORDMAP.json.example` is the reference file operators copy to
`WORDMAP.json`. If it becomes malformed or loses required structure, the
scorer silently falls back to built-in keywords, which can mask a real
misconfiguration — so a broken example file must not pass this gate
quietly. It had no test.

Each of the eight documented rules is injected directly into a real copy of
the repository's own `WORDMAP.json.example` (loaded and mutated as JSON,
not a synthetic minimal fixture), so the injections also prove the gate's
field names and structure assumptions still match the real file.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess  # nosec B404 — runs the gate under test, fixed argument list
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "ci" / "gate_h_wordmap_schema.py"
EXAMPLE = REPO / "WORDMAP.json.example"


@pytest.fixture
def real_data() -> dict[str, Any]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


@pytest.fixture
def mirror(tmp_path: Path) -> Path:
    """A disposable repository holding the real gate and the real wordmap."""
    root = tmp_path / "repo"
    (root / "scripts" / "ci").mkdir(parents=True)
    shutil.copy2(GATE, root / "scripts" / "ci" / GATE.name)
    shutil.copy2(EXAMPLE, root / EXAMPLE.name)
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — fixed argument list, no shell
        [sys.executable, str(root / "scripts" / "ci" / GATE.name)],
        capture_output=True,
        text=True,
        check=False,
        cwd=root,
    )


def _write(root: Path, data: Any) -> None:
    (root / EXAMPLE.name).write_text(json.dumps(data, indent=2), encoding="utf-8")


class TestTheMirrorIsFaithful:
    def test_an_untouched_mirror_passes(self, mirror: Path) -> None:
        result = _run(mirror)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "PASS" in result.stdout

    def test_a_missing_file_fails(self, mirror: Path) -> None:
        (mirror / EXAMPLE.name).unlink()
        result = _run(mirror)
        assert result.returncode == 1
        assert "not found" in result.stdout


class TestEachDocumentedRule:
    def test_invalid_json_fails(self, mirror: Path) -> None:
        (mirror / EXAMPLE.name).write_text("{not valid json", encoding="utf-8")
        result = _run(mirror)
        assert result.returncode == 1
        assert "not valid JSON" in result.stdout

    def test_missing_nuclear_risk_key_fails(self, mirror: Path, real_data: dict) -> None:
        data = copy.deepcopy(real_data)
        del data["nuclear_risk"]
        _write(mirror, data)
        result = _run(mirror)
        assert result.returncode == 1
        assert "nuclear_risk" in result.stdout

    def test_nuclear_risk_as_a_list_instead_of_object_fails(self, mirror: Path, real_data: dict) -> None:
        data = copy.deepcopy(real_data)
        data["nuclear_risk"] = ["not", "a", "dict"]
        _write(mirror, data)
        result = _run(mirror)
        assert result.returncode == 1
        assert "must be a JSON object" in result.stdout

    def test_an_uppercase_category_name_fails(self, mirror: Path, real_data: dict) -> None:
        data = copy.deepcopy(real_data)
        data["nuclear_risk"]["BadCategoryName"] = {"placeholder term": 5.0}
        _write(mirror, data)
        result = _run(mirror)
        assert result.returncode == 1
        assert "BadCategoryName" in result.stdout
        assert "lowercase" in result.stdout

    def test_a_category_that_is_not_an_object_fails(self, mirror: Path, real_data: dict) -> None:
        data = copy.deepcopy(real_data)
        first = next(iter(data["nuclear_risk"]))
        data["nuclear_risk"][first] = ["not", "a", "dict"]
        _write(mirror, data)
        result = _run(mirror)
        assert result.returncode == 1
        assert first in result.stdout

    def test_an_empty_category_fails(self, mirror: Path, real_data: dict) -> None:
        data = copy.deepcopy(real_data)
        first = next(iter(data["nuclear_risk"]))
        data["nuclear_risk"][first] = {}
        _write(mirror, data)
        result = _run(mirror)
        assert result.returncode == 1
        assert "no keywords" in result.stdout

    def test_an_empty_keyword_string_fails(self, mirror: Path, real_data: dict) -> None:
        data = copy.deepcopy(real_data)
        first = next(iter(data["nuclear_risk"]))
        data["nuclear_risk"][first][""] = 5.0
        _write(mirror, data)
        result = _run(mirror)
        assert result.returncode == 1
        assert "non-empty string" in result.stdout

    def test_a_keyword_over_the_length_limit_fails(self, mirror: Path, real_data: dict) -> None:
        data = copy.deepcopy(real_data)
        first = next(iter(data["nuclear_risk"]))
        data["nuclear_risk"][first]["x" * 250] = 5.0
        _write(mirror, data)
        result = _run(mirror)
        assert result.returncode == 1
        assert "exceeds" in result.stdout

    def test_a_non_numeric_weight_fails(self, mirror: Path, real_data: dict) -> None:
        data = copy.deepcopy(real_data)
        first = next(iter(data["nuclear_risk"]))
        data["nuclear_risk"][first]["injected term"] = "not a number"
        _write(mirror, data)
        result = _run(mirror)
        assert result.returncode == 1
        assert "must be a number" in result.stdout

    def test_a_weight_above_ten_fails(self, mirror: Path, real_data: dict) -> None:
        data = copy.deepcopy(real_data)
        first = next(iter(data["nuclear_risk"]))
        data["nuclear_risk"][first]["injected term"] = 10.5
        _write(mirror, data)
        result = _run(mirror)
        assert result.returncode == 1
        assert "outside valid range" in result.stdout

    def test_a_negative_weight_fails(self, mirror: Path, real_data: dict) -> None:
        data = copy.deepcopy(real_data)
        first = next(iter(data["nuclear_risk"]))
        data["nuclear_risk"][first]["injected term"] = -1.0
        _write(mirror, data)
        result = _run(mirror)
        assert result.returncode == 1
        assert "outside valid range" in result.stdout

    def test_too_few_categories_fails(self, mirror: Path, real_data: dict) -> None:
        data = copy.deepcopy(real_data)
        keep = dict(list(data["nuclear_risk"].items())[:2])
        assert len(keep) < 5, "the real file must have more than 2 categories for this injection to mean anything"
        data["nuclear_risk"] = keep
        _write(mirror, data)
        result = _run(mirror)
        assert result.returncode == 1
        assert "categories" in result.stdout
        assert "truncation" in result.stdout

    def test_too_few_total_keywords_fails(self, mirror: Path, real_data: dict) -> None:
        data = copy.deepcopy(real_data)
        # Keep every category (so the category-count rule doesn't also fire)
        # but strip each down to one keyword, well under the 20-keyword floor.
        for category, keywords in data["nuclear_risk"].items():
            first_kw = next(iter(keywords))
            data["nuclear_risk"][category] = {first_kw: keywords[first_kw]}
        n_categories = len(data["nuclear_risk"])
        assert n_categories >= 5, "need enough categories that only the keyword-count rule fires"
        assert n_categories < 20, "the keyword injection must actually be below the 20-keyword floor"
        _write(mirror, data)
        result = _run(mirror)
        assert result.returncode == 1
        assert "keywords" in result.stdout
        assert "truncation" in result.stdout
