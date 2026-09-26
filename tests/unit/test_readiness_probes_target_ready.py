# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""A readiness probe that hits `/health` can never fail.

`/health` (`health_check_service.py::liveness`, mounted at app level) answers
200 whenever the process is alive at all -- that is what makes it a correct
LIVENESS check, and exactly why it is the wrong target for READINESS: a probe
whose only job is "should this pod receive traffic" must be able to say no.

`core/health.py::readiness_probe`, mounted at `/ready`, is the one that can:
it checks `app_state.initialized`, a live `SELECT 1`, the schema-verification
state the startup fix added (503 `schema_unverified` when the DB is not at the
migrated head — see `docs/ai/MASTER_OUTSTANDING.md` §A11), and lockdown state.

`k8s/k8s-deployment.yaml`'s readinessProbe pointed at `/health`, so it could
never remove a pod from the Service even while its schema was unverified. Same
defect, same fix, in `deployments/k8s/deployment.yaml` (which pointed at
`/health/ready` -- a real endpoint, but one that checks redis/db/data_feed and
NOT the schema/lockdown state `/ready` was built for).

This test parses the manifests as text rather than loading Helm's chart
(`helm template` is not available in this environment, and a Helm template is
not valid stand-alone YAML once it uses `{{- if }}` control blocks elsewhere in
the file) — same approach already used by
`tests/system/test_deployment_infrastructure.py` for the same reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every manifest a probe-carrying Deployment/StatefulSet could live in.
_MANIFEST_ROOTS = (
    REPO_ROOT / "k8s",
    REPO_ROOT / "deployments" / "k8s",
    REPO_ROOT / "helm" / "hopefx" / "templates",
)


def _manifest_files() -> list[Path]:
    files: list[Path] = []
    for root in _MANIFEST_ROOTS:
        if root.is_dir():
            files.extend(sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml")))
    return files


def _indented_block(text: str, key: str) -> list[str]:
    """Every block introduced by a `<key>:` line, as the lines strictly more
    indented than it -- works on plain YAML and on a Helm template whose
    probe block itself uses no control structures (`{{- if }}`/`{{- range }}`),
    which is true of every probe block in this repository today.
    """
    lines = text.splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if stripped.rstrip() == f"{key}:":
            body: list[str] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                if nxt.strip() == "":
                    body.append(nxt)
                    j += 1
                    continue
                nxt_indent = len(nxt) - len(nxt.lstrip(" "))
                if nxt_indent <= indent:
                    break
                body.append(nxt)
                j += 1
            blocks.append("\n".join(body))
            i = j
        else:
            i += 1
    return blocks


_HELM_VALUES = yaml.safe_load((REPO_ROOT / "helm" / "hopefx" / "values.yaml").read_text(encoding="utf-8"))


def _resolve_helm_value(expr: str) -> str:
    """`{{ .Values.probes.readiness.path }}` -> the value.yaml value it renders to."""
    match = re.search(r"\.Values\.([\w.]+)", expr)
    if not match:
        return expr
    node = _HELM_VALUES
    for part in match.group(1).split("."):
        assert isinstance(node, dict) and part in node, f"{expr!r} names a key values.yaml does not have: {part!r}"
        node = node[part]
    return str(node)


def _http_get_path(probe_block: str) -> str | None:
    """The `httpGet.path` of a probe block, resolving one Helm value reference.

    Returns None for a probe with no `httpGet` (an `exec`-based probe, which
    cannot target a URL path at all and is out of this test's scope).
    """
    http_blocks = _indented_block(probe_block, "httpGet")
    if not http_blocks:
        return None
    match = re.search(r"^\s*path:\s*(\S.*)$", http_blocks[0], re.MULTILINE)
    assert match, f"httpGet probe has no `path:`:\n{probe_block}"
    raw = match.group(1).strip()
    if "{{" in raw:
        return _resolve_helm_value(raw)
    return raw


def test_the_scan_finds_readiness_probes():
    """Positive control (F255 shape): a scan that matches nothing agrees with
    every assertion below."""
    found = 0
    for path in _manifest_files():
        found += len(_indented_block(path.read_text(encoding="utf-8"), "readinessProbe"))
    assert found >= 2, f"expected at least the API deployment's readiness probes, found {found}"


@pytest.mark.parametrize("path", _manifest_files(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_every_httpget_readiness_probe_targets_ready(path: Path):
    """`/health` always answers 200 -- a readiness probe pointed at it can never
    fail, which is the exact defect this test exists to catch (§A11)."""
    text = path.read_text(encoding="utf-8")
    for block in _indented_block(text, "readinessProbe"):
        http_path = _http_get_path(block)
        if http_path is None:
            continue  # exec-based probe (e.g. a heartbeat-file check) -- not an HTTP path.
        assert http_path == "/ready", (
            f"{path.relative_to(REPO_ROOT)}: readinessProbe httpGet targets {http_path!r}, "
            "not '/ready' -- it will not reflect schema verification, startup "
            "completion or lockdown state (MASTER_OUTSTANDING.md §A11)"
        )


@pytest.mark.parametrize("path", _manifest_files(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_every_httpget_liveness_probe_stays_cheap(path: Path):
    """Liveness must NOT be pointed at `/ready`: a schema that fails
    verification should crash-loop-restart the pod at most once (startupProbe
    already refuses to pass it traffic), never restart it forever because a
    slow-to-verify schema keeps tripping liveness too.
    """
    text = path.read_text(encoding="utf-8")
    for block in _indented_block(text, "livenessProbe"):
        http_path = _http_get_path(block)
        if http_path is None:
            continue
        assert http_path != "/ready", (
            f"{path.relative_to(REPO_ROOT)}: livenessProbe httpGet targets '/ready' -- a pod that cannot verify "
            "its schema would be killed and restarted forever instead of just held out of the Service"
        )
        assert http_path == "/health", (
            f"{path.relative_to(REPO_ROOT)}: livenessProbe httpGet targets {http_path!r}, expected the cheap "
            "always-OK-if-alive '/health' endpoint"
        )
