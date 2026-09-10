# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""What the audit log does when it cannot write, and what its verifier checks.

`ImmutableAuditLog` is the SEC/CFTC trade-reporting chain. Its value is entirely
in being able to say "this is every action, and none of it was altered". Two
things have to hold for that: a write that fails must be noticed, and the
verifier must check the artefact a regulator would be handed.

Neither held (STRIDE-R).

* **The async write's exception was discarded.** `_persist_record` schedules
  `_async_write` with `add_done_callback(lambda _: None)` — a callback that
  throws the task's result away, exceptions included. Under FastAPI there IS a
  running loop, so the async path is the one production takes.

  Not *silent*, precisely: asyncio eventually emits "Task exception was never
  retrieved" when the task is garbage-collected. That is not a substitute. It
  arrives at an unpredictable time, from the `asyncio` logger, with no record
  identity, no actor and no action — nothing an operator would attribute to the
  compliance chain. (It is also what made the first draft of the async test
  below pass for the wrong reason: the traceback repr contains the path
  `compliance/auditor.py`, so a naive `"audit" in message` check matched
  asyncio's warning rather than anything this module said. The assertion now
  requires a record from the `compliance.auditor` logger itself.)

  The sync fallback, which only runs without a loop, already logged at ERROR.

* **`verify_integrity()` reads `self.records`** — the in-memory list. A record
  that failed to persist is still in it, so the chain verifies clean while the
  file on disk is missing an entry. The check verifies a copy that cannot
  disagree with itself (F176: a measurement that cannot fail), and never looks
  at the file it is supposed to be attesting.

Together: a superadmin action taken during an audit-storage outage leaves no
error, and the integrity check still returns True.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]


@pytest.fixture
def log(tmp_path):
    from compliance.auditor import ImmutableAuditLog

    inst = ImmutableAuditLog()
    inst.log_path = str(tmp_path) + "/"
    return inst


def _append(inst, action="halt_trading", actor="ops-ren"):
    from compliance.auditor import AuditLevel

    return inst.append(
        level=AuditLevel.CRITICAL,
        category="superadmin",
        actor=actor,
        action=action,
        data={"reason": "manual"},
    )


class TestTheHarnessIsLive:
    """Every assertion below is about a failure path. If the happy path is
    broken, none of them mean anything."""

    def test_a_record_is_written_and_verifies(self, log, tmp_path):
        _append(log)

        files = list(Path(tmp_path).glob("audit_*.jsonl"))
        assert files, "nothing was persisted at all — the assertions below are vacuous"
        assert log.verify_integrity() is True


class TestAFailedWriteIsAnnounced:
    def test_an_uncreatable_log_directory_does_not_raise_into_the_caller(self, log, caplog):
        """`_persist_record` calls `mkdir(parents=True)` OUTSIDE the try that
        guards the write. An unwritable location therefore raised
        FileNotFoundError straight into `append()` — so the audit write could
        crash the very superadmin action it was recording, while an ordinary
        write failure was swallowed. Two opposite behaviours for one fault."""
        log.log_path = "/proc/nonexistent-directory-that-cannot-be-created/"

        caplog.set_level(logging.INFO, logger="compliance.auditor")
        try:
            _append(log)
        except Exception as exc:
            pytest.fail(f"a failed audit write raised into the caller: {exc!r}")

        loud = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert loud, "the audit log could not be written and nothing above DEBUG said so"

    @pytest.mark.asyncio
    async def test_an_async_write_failure_is_logged_at_error(self, log, caplog):
        """The path production takes. Under FastAPI there IS a running loop, so
        `_persist_record` schedules `_async_write` — and its exception was
        thrown away by a done-callback that ignored the result."""
        caplog.set_level(logging.INFO, logger="compliance.auditor")

        async def _boom(*_a, **_k):
            raise OSError("no space left on device")

        log._async_write = _boom
        _append(log)

        # Let the scheduled task run and its callback fire.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        # From THIS module, not asyncio's generic GC warning — which fires at
        # an unpredictable time, names no record, and whose traceback repr
        # contains "compliance/auditor.py", so a substring check on the message
        # matches it and proves nothing.
        ours = [r for r in caplog.records if r.levelno >= logging.ERROR and r.name == "compliance.auditor"]
        assert ours, "the audit log failed to persist a superadmin action and this module said nothing"
        msg = " ".join(r.getMessage() for r in ours)
        assert "halt_trading" in msg or "ops-ren" in msg, (
            f"the error does not identify the lost record, so an operator cannot act on it: {msg!r}"
        )


class TestVerificationChecksThePersistedLog:
    def test_it_can_verify_the_file_not_only_memory(self, log, tmp_path):
        """A verifier that reads its own memory attests nothing about the
        artefact a regulator receives."""
        _append(log, action="first")
        _append(log, action="second")

        assert hasattr(log, "verify_persisted_integrity")
        assert log.verify_persisted_integrity() is True

    def test_a_record_missing_from_the_file_is_detected(self, log, tmp_path):
        """The STRIDE-R case: the write failed, memory advanced, the file has a
        gap. In-memory verification cannot see it — this must."""
        _append(log, action="first")
        _append(log, action="second")
        _append(log, action="third")

        path = next(Path(tmp_path).glob("audit_*.jsonl"))
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 3, "the harness did not persist three records"
        path.write_text(lines[0] + "\n" + lines[2] + "\n")  # drop the middle

        assert log.verify_integrity() is True, "in-memory verification is expected to miss this"
        assert log.verify_persisted_integrity() is False, (
            "a record missing from the persisted log verified clean — the chain attests nothing"
        )

    def test_altering_the_hashed_payload_is_detected(self, log, tmp_path):
        """`data` IS covered by the chain."""
        _append(log, action="halt_trading")

        path = next(Path(tmp_path).glob("audit_*.jsonl"))
        row = json.loads(path.read_text().strip())
        row["data"] = {"reason": "something else entirely"}
        path.write_text(json.dumps(row) + "\n")

        assert log.verify_persisted_integrity() is False, "an edited payload verified clean"

    @pytest.mark.parametrize("field", ["actor", "action", "level", "category"])
    def test_the_chain_does_not_cover_who_did_what(self, log, tmp_path, field):
        """PINNED AS OBSERVED, NOT ENDORSED — and this is the serious one.

        `_calculate_hash` hashes exactly four things:

            {"seq", "prev_hash", "timestamp", "data_hash"}

        `actor`, `action`, `level` and `category` are stored in the record and
        in the log file, and NONE of them is covered by the chain. Rewriting
        who performed an action, or what the action was, leaves a log that
        verifies clean.

        For a SEC/CFTC trade-reporting chain, "who did what" is the entire
        point of the artefact. `data` is covered; the attribution is not.

        Not changed here: widening the hash input invalidates every record
        already written, so it needs a versioned record format and a migration
        — a decision about a compliance artefact, not a bug fix. Filed. When it
        is made, this test flips to asserting detection and its parametrisation
        becomes the list of fields now covered.
        """
        _append(log, action="halt_trading", actor="ops-ren")

        path = next(Path(tmp_path).glob("audit_*.jsonl"))
        row = json.loads(path.read_text().strip())
        assert field in row, f"{field} is not even stored — update this test"
        row[field] = "TAMPERED"
        path.write_text(json.dumps(row) + "\n")

        assert log.verify_persisted_integrity() is True, (
            f"{field} is now covered by the hash chain — that is the fix; update this test and close the task"
        )

    def test_an_empty_log_is_not_reported_as_verified(self, log):
        """Nothing to verify is not the same as verified. Rule 2: an unmeasured
        value is absent, never best-case."""
        assert log.verify_persisted_integrity() is None
