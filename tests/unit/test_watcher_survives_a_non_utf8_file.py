# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""One unreadable file must not take out a whole department's watcher.

Observed on an operator's machine 2026-09-19, repeating on every awareness
cycle:

    ERROR [ai.awareness.watchers] ai.awareness: watcher
    platform_engineering/broken_imports failed -- this department is not
    watching for it right now
    ...
    UnicodeDecodeError: 'utf-8' codec can't decode byte 0xa4 in position 64

`check_broken_imports` catches `SyntaxError` and `OSError` and records each as
a finding, deliberately, so a file that will not parse cannot survive an audit
by being skipped. `UnicodeDecodeError` derives from `ValueError`, so it matched
neither handler: a single non-UTF-8 byte anywhere in the tree aborted the scan
of every remaining file and disabled the control.

That is the shape this repository keeps finding -- a control that exists, reads
correctly, and is not running -- arriving here through an exception hierarchy
rather than through a guard.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def _sample_tree(root):
    """A parseable module, plus one whose bytes are not valid UTF-8."""
    (root / "fine.py").write_text("import os\n", encoding="utf-8")
    # 0xa4 is the byte from the operator's traceback. Latin-1 text committed by
    # an editor that did not ask, which is how these actually appear.
    (root / "latin1.py").write_bytes(b"# -*- coding: latin-1 -*-\n# currency sign: \xa4\nimport os\n")


def test_a_non_utf8_file_does_not_abort_the_scan(tmp_path):
    from ai.departments.platform_engineering import check_broken_imports

    _sample_tree(tmp_path)

    result = check_broken_imports(root=str(tmp_path))

    assert result.get("available") is not False, (
        f"the watcher reported itself unavailable instead of scanning: {result}"
    )
    assert result["files_scanned"] >= 2, (
        f"the scan stopped early -- only {result.get('files_scanned')} files reached, so the "
        "undecodable file aborted the walk instead of being recorded"
    )


def test_the_undecodable_file_is_reported_rather_than_skipped(tmp_path):
    """Recording it is the point: skipping is how it survives a hundred audits.

    The module's own comment says exactly that about `SyntaxError`. A file whose
    bytes cannot be read is at least as much of a finding as one that cannot be
    parsed.
    """
    from ai.departments.platform_engineering import check_broken_imports

    _sample_tree(tmp_path)

    result = check_broken_imports(root=str(tmp_path))
    flagged = {entry["file"] for entry in result.get("unparseable", [])}

    assert any(f.endswith("latin1.py") for f in flagged), (
        f"the undecodable file was not reported as unparseable: {result.get('unparseable')}"
    )
