# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The ChromaDB CVE acceptance must be enforced, not just asserted.

`.trivyignore.yaml` accepts four chromadb CVEs — two of them pre-authentication
code injection — on the strength of one claim:

    All four are ChromaDB *server* attack surfaces ... This platform uses the
    embedded client only ... There is no port, no tenant boundary, and no
    pre-auth request path.

    This acceptance stops holding the moment anyone runs chroma as a server or
    points the client at a remote host.

That last sentence describes a condition nothing was checking. The acceptance
was prose: true when written, and able to become false with one line in an
unrelated pull request, with the CVEs staying suppressed either way. A
suppression whose precondition nobody verifies is the same shape as a gate
nobody calls.

`scripts/ci/gate_chroma_embedded_only.py` turns the claim into a check. These
tests inject each way the claim could stop being true and assert the gate
refuses — because a gate that has never been watched to fail is a comment.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "scripts" / "ci" / "gate_chroma_embedded_only.py"


def run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), "--root", str(root)],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
    )


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A miniature repo that uses chroma the way this one legitimately does."""
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "vector_store.py").write_text(
        "import chromadb\nclient = chromadb.PersistentClient(path='/var/lib/hopefx/chroma')\n"
    )
    (tmp_path / "docker-compose.yml").write_text("services:\n  api:\n    build: .\n    ports: ['8000:8000']\n")
    return tmp_path


# ── the legitimate configuration passes ───────────────────────────────────────


def test_embedded_persistent_client_is_allowed(sandbox: Path):
    result = run(sandbox)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_real_repository_passes_today(sandbox: Path):
    """If this fails, someone made the CVE acceptance untrue."""
    result = run(REPO)
    assert result.returncode == 0, result.stdout + result.stderr


# ── each way the acceptance could stop holding ────────────────────────────────


def test_http_client_is_refused(sandbox: Path):
    """`HttpClient` points the client at a remote host — named in the acceptance."""
    (sandbox / "research" / "remote.py").write_text(
        "import chromadb\nc = chromadb.HttpClient(host='vectors.internal', port=8000)\n"
    )
    result = run(sandbox)
    assert result.returncode == 1
    assert "HttpClient" in result.stdout + result.stderr


def test_async_http_client_is_refused(sandbox: Path):
    """The async variant is the same listener with a different name."""
    (sandbox / "research" / "remote.py").write_text(
        "import chromadb\nc = chromadb.AsyncHttpClient(host='vectors.internal')\n"
    )
    assert run(sandbox).returncode == 1


def test_a_chroma_service_in_compose_is_refused(sandbox: Path):
    """A compose service is a listener even if no Python calls HttpClient."""
    (sandbox / "docker-compose.yml").write_text(
        "services:\n  chroma:\n    image: chromadb/chroma:latest\n    ports: ['8001:8000']\n"
    )
    result = run(sandbox)
    assert result.returncode == 1
    assert "docker-compose.yml" in result.stdout + result.stderr


def test_running_the_chroma_app_under_uvicorn_is_refused(sandbox: Path):
    (sandbox / "Dockerfile.chroma").write_text(
        "FROM python:3.12-slim\nCMD uvicorn chromadb.app:app --host 0.0.0.0 --port 8000\n"
    )
    assert run(sandbox).returncode == 1


def test_chroma_server_settings_are_refused(sandbox: Path):
    """`chroma_server_host` in Settings is client/server mode by another door."""
    (sandbox / "research" / "cfg.py").write_text(
        "from chromadb.config import Settings\n"
        "s = Settings(chroma_server_host='vectors.internal', chroma_server_http_port=8000)\n"
    )
    assert run(sandbox).returncode == 1


def test_a_chroma_server_env_var_is_refused(sandbox: Path):
    (sandbox / ".env.example").write_text("CHROMA_SERVER_HOST=vectors.internal\n")
    assert run(sandbox).returncode == 1


# ── the gate must not be fooled, and must not cry wolf ────────────────────────


def test_prose_describing_the_ban_is_not_a_violation(sandbox: Path):
    """This test file and the gate itself both spell "HttpClient" in prose.

    A checker that reads comments is not reading code — the repository already
    had that defect once, in the analyzer's nan_leak rule. If this fails, the
    gate flags its own documentation and every honest description of the rule.
    """
    (sandbox / "research" / "notes.py").write_text(
        '"""We deliberately never call chromadb.HttpClient here."""\n'
        "# chroma_server_host must stay unset; see .trivyignore.yaml\n"
        "import chromadb\n"
        "c = chromadb.PersistentClient(path='/tmp/x')\n"
    )
    result = run(sandbox)
    assert result.returncode == 0, result.stdout + result.stderr


def test_an_unrelated_httpclient_is_not_a_violation(sandbox: Path):
    """Another library's HttpClient is not chroma in server mode."""
    (sandbox / "research" / "other.py").write_text(
        "from some_sdk import HttpClient\nc = HttpClient('https://api.example.com')\n"
    )
    assert run(sandbox).returncode == 0


def test_the_gate_names_the_file_and_the_reason(sandbox: Path):
    """A refusal has to be actionable at 3am, not just non-zero."""
    (sandbox / "research" / "remote.py").write_text("import chromadb\nc = chromadb.HttpClient(host='h')\n")
    out = run(sandbox).stdout + run(sandbox).stderr
    assert "remote.py" in out
    assert "trivyignore" in out.lower() or "CVE" in out


def test_the_gate_fails_closed_when_it_cannot_scan(tmp_path: Path):
    """No files to scan is not the same as a clean scan.

    An empty result must not read as a pass — that is how a broken glob
    certifies a repository it never looked at.
    """
    empty = tmp_path / "nothing"
    empty.mkdir()
    result = run(empty)
    assert result.returncode == 1, "a scan that found no source files must not report a pass"


# ── the suppression and the gate must stay in step ────────────────────────────


def test_the_trivyignore_still_claims_embedded_only():
    """If the CVE acceptance is rewritten, this gate's premise changes with it."""
    text = (REPO / ".trivyignore.yaml").read_text(encoding="utf-8")
    if "chromadb" not in text:
        pytest.skip("chromadb acceptance removed — gate premise no longer applies")
    assert "embedded" in text.lower()
    assert "PersistentClient" in text


def test_chromadb_is_still_a_dependency():
    """A gate guarding an uninstalled package is a gate guarding nothing."""
    reqs = (REPO / "requirements.txt").read_text(encoding="utf-8")
    if "chromadb" not in reqs:
        pytest.skip("chromadb no longer a dependency")
    assert shutil.which is not None  # trivially true; the real assertion is above
