# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`--generate` wrote TOML it could not read back.

`docs/GATE_EVIDENCE.toml` is the Rule 1 ratchet: every gate ships with evidence
it can fail, or it is treated as absent. The `evidence`, `injected` and `note`
fields are written by humans and preserved across regeneration — and they were
preserved by interpolating them straight into a TOML basic string:

    f'injected = "{prior.injected}"'

`gate_d_model_accuracy`'s row contains a quoted phrase. Regenerating produced

    tomllib.TOMLDecodeError: Expected newline or end of document

so the ledger stopped parsing, and every subsequent `--check` failed before it
could report anything. The ratchet that proves the gates work is itself a file
one command corrupts.

Found by running `--generate` to add a row for a new gate — which is the
documented way to add one, so this was on the path everybody takes.

A backslash does the same thing more quietly: it would be read back as an escape
sequence, silently changing the recorded text rather than failing loudly.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import tomllib

import pytest

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def ge():
    spec = importlib.util.spec_from_file_location("gate_evidence_rt", REPO / "scripts" / "gate_evidence.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


AWKWARD = [
    'it "validates 38 MB of artefacts resolved from __file__"',
    r"a Windows path C:\Users\x and a regex \d+",
    'both "quoted" and \\ backslashed',
    "a\ttab and a newline is not expected but a\\nliteral backslash-n is",
]


class TestTheEscaper:
    @pytest.mark.parametrize("value", AWKWARD)
    def test_a_value_survives_a_round_trip(self, ge, value: str) -> None:
        document = f'[[gate]]\nid = "x"\ninjected = {ge.toml_string(value)}\n'
        parsed = tomllib.loads(document)
        assert parsed["gate"][0]["injected"] == value

    def test_an_ordinary_value_is_not_mangled(self, ge) -> None:
        assert ge.toml_string("plain text") == '"plain text"'


class TestRegenerationPreservesWhatHumansWrote:
    def test_the_real_ledger_round_trips(self, ge, tmp_path) -> None:
        """Regenerate the committed ledger into a temp file and re-parse it.

        The committed file parses today. The question is whether it still parses
        after the tool rewrites it, which is the operation that broke it.
        """
        source = REPO / "docs" / "GATE_EVIDENCE.toml"
        before = tomllib.loads(source.read_text(encoding="utf-8"))

        destination = tmp_path / "GATE_EVIDENCE.toml"
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        ge.generate(repo=REPO, ledger=destination)

        after = tomllib.loads(destination.read_text(encoding="utf-8"))

        by_id_before = {g["id"]: g for g in before["gate"]}
        by_id_after = {g["id"]: g for g in after["gate"]}
        for gate_id, row in by_id_before.items():
            assert gate_id in by_id_after, f"{gate_id} was dropped by regeneration"
            for field in ("evidence", "injected", "note"):
                if field in row:
                    assert by_id_after[gate_id].get(field) == row[field], (
                        f"{gate_id}.{field} changed across regeneration"
                    )


class TestAGateWrittenAsAModuleIsNotExempt:
    """Discovery matched `scripts/*.py` and nothing else.

    A hook whose entry is `python -m deployment.change_records` is a gate by
    every meaning of the word — it runs in `.pre-commit-config.yaml`, it blocks
    a commit, and Rule 1 says it ships with evidence it can fail. Discovery did
    not see it, so it was silently exempt: the ledger reported the same count
    before and after it was added, and `--check` passed.

    A hole in the gate that enforces gates is the worst place for one, because
    every other gate's evidence is only as trustworthy as the census of gates.
    """

    def test_the_change_record_hook_is_discovered(self, ge) -> None:
        ids = {g.id for g in ge.discover_gates(REPO)}
        assert "change-record" in ids, sorted(ids)

    def test_a_module_entry_records_what_it_runs(self, ge) -> None:
        gate = next(g for g in ge.discover_gates(REPO) if g.id == "change-record")
        assert "deployment" in gate.runs and "change_records" in gate.runs

    def test_script_entries_still_resolve(self, ge) -> None:
        # The existing form must keep working; this widens discovery, it does
        # not replace it.
        gate = next(g for g in ge.discover_gates(REPO) if g.id == "adr-check")
        assert gate.runs.endswith("adr.py")
