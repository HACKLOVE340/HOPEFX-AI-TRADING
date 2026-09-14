# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The manifests the tests read are not the manifests ArgoCD deploys.

Two suites in this directory verify the platform's safety posture:

* `test_configmaps_do_not_contradict_on_safety.py` — nine tests over `k8s/` and
  `deployments/k8s/`, proving `HOPEFX_INVARIANT_MODE`, `DRIFT_BLOCK` and
  `STALE_MODEL_BLOCK` are stated explicitly and never weakened.
* `test_kill_switch_layers_survive_deployment.py` — fourteen tests over the same
  two trees, proving layer 5 of the kill switch has a ConfigMap to patch, RBAC
  that grants it, and a ServiceAccount the RoleBinding names.

Twenty-three passing tests. `k8s/argocd-app.yaml` deploys neither tree:

    spec.source.path: helm/hopefx

`helm/hopefx` is a different set of manifests, and measured against it every one
of those guarantees is absent:

| Control | `k8s/` | `helm/hopefx` (deployed) |
|---|---|---|
| `HOPEFX_INVARIANT_MODE` | `enforce` | **unset** → `monitor` |
| `DRIFT_BLOCK` | `true` | **unset** → `false` |
| `STALE_MODEL_BLOCK` | `true` | **unset** → `true` (the one safe default) |
| kill-switch ConfigMap | present | **absent** |
| kill-switch RBAC + ServiceAccount | present | **absent** |

Each default proven by execution, not read:

    >>> from invariants import enforcement; enforcement._DEFAULT_MODE
    'monitor'
    >>> from ml import inference_engine as ie; ie._DRIFT_BLOCK, ie._STALE_MODEL_BLOCK
    (False, True)

So the cluster ArgoCD builds runs its constitutional invariants in monitor —
they observe and never refuse — trades on drifted models, and has no object for
the kill switch's Redis-outage fallback to patch and no RBAC to reach one. And
`syncPolicy.automated.prune: true` means ArgoCD **deletes** a kill-switch
ConfigMap applied out-of-band from `k8s/`, because it is not in the chart.

This is the shape `hopefx-dead-controls` calls *a measurement that cannot fail*.
The twenty-three tests are correct, careful, and aimed at trees the deployer
does not use, so they report full coverage of a posture that is not deployed.

These tests follow `spec.source.path` rather than naming a directory, so
repointing ArgoCD moves the assertions with it instead of silently emptying
them.

That sentence was written before it was true, and the gap was the same defect
one level up. The assertions iterated synced paths that contain a `Chart.yaml`;
a path without one produced an EMPTY list, and every `assert not missing` then
passed over nothing. Measured by repointing `spec.source.path`:

    docs         one yaml, no manifest, no posture  ->  all 7 tests passed
    invariants   no yaml at all                     ->  all 7 tests passed

Both are the original P0 exactly — ArgoCD syncing a path that carries none of
the safety posture — and the suite written to catch it reported success. It now
reads a plain directory of manifests as well as a chart, and
`test_every_synced_path_is_checkable` fails when a synced path yields neither.
The same repoints now fail 5 and 6 of 8.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Keys whose absence or downgrade weakens a control. Same list as the ConfigMap
#: suite, deliberately — a key that must be explicit in one deployment path must
#: be explicit in all of them.
SAFETY_KEYS: tuple[str, ...] = ("HOPEFX_INVARIANT_MODE", "DRIFT_BLOCK", "STALE_MODEL_BLOCK")

KILL_SWITCH_CONFIGMAP = "hopefx-kill-switch"


def _yaml(path: Path):
    import yaml

    return list(yaml.safe_load_all(path.read_text(encoding="utf-8")))


def _deployed_paths() -> list[str]:
    """Every `spec.source.path` any ArgoCD Application in this repo syncs."""
    import yaml

    paths: list[str] = []
    for candidate in sorted(REPO_ROOT.rglob("*.yaml")):
        rel = candidate.relative_to(REPO_ROOT).as_posix()
        if rel.startswith((".venv/", "node_modules/", "helm/hopefx/charts/")):
            continue
        try:
            docs = _yaml(candidate)
        except (yaml.YAMLError, UnicodeDecodeError, OSError):
            continue
        for doc in docs:
            if not isinstance(doc, dict) or doc.get("kind") != "Application":
                continue
            source = (doc.get("spec") or {}).get("source") or {}
            path = source.get("path")
            if path:
                paths.append(str(path).strip("/"))
    return sorted(set(paths))


def test_the_scan_finds_what_the_deployer_syncs():
    """A scan that matches nothing agrees with every assertion below (F255).

    This is the positive control, and it earned its place: the first draft of
    the sibling suite iterated a helper that yields `(filename, doc)` pairs as
    if it yielded bare documents, matched zero Applications, and passed every
    assertion vacuously.
    """
    paths = _deployed_paths()
    assert paths, "no ArgoCD Application declares a source path — the scan is wrong, or the deployer changed"
    for path in paths:
        assert (REPO_ROOT / path).is_dir(), f"ArgoCD syncs {path!r}, which is not a directory in this repo"


def _chart_values(chart: Path) -> dict:
    values = chart / "values.yaml"
    if not values.is_file():
        return {}
    docs = [d for d in _yaml(values) if isinstance(d, dict)]
    return docs[0] if docs else {}


def _chart_env(chart: Path) -> dict[str, str]:
    """`templates/deployment.yaml` expands `.Values.env` wholesale into `env:`."""
    env = _chart_values(chart).get("env") or {}
    return {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {}


def _plain_env(root: Path) -> dict[str, str]:
    """Env from ordinary manifests: ConfigMap `data`, and literal container env."""
    env: dict[str, str] = {}
    for candidate in sorted(root.rglob("*.yaml")):
        try:
            docs = _yaml(candidate)
        except Exception:
            continue
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            if doc.get("kind") == "ConfigMap" and isinstance(doc.get("data"), dict):
                env.update({str(k): str(v) for k, v in doc["data"].items()})
            for container in _containers(doc):
                for item in container.get("env") or []:
                    if isinstance(item, dict) and "name" in item and "value" in item:
                        env[str(item["name"])] = str(item["value"])
    return env


def _containers(doc: dict) -> list[dict]:
    spec = (doc.get("spec") or {}).get("template", {}).get("spec", {})
    out = [c for c in (spec.get("containers") or []) if isinstance(c, dict)]
    return out


def _deployed_targets() -> list[tuple[str, dict[str, str], str]]:
    """Every synced path as (path, resolved env, the text of its manifests).

    A synced path is checked whether or not it is a Helm chart. `_charts()`
    filtered to paths containing a Chart.yaml, and every assertion below then
    iterated that list — so pointing ArgoCD at anything without one left the
    list EMPTY and each `assert not missing` passed over nothing. Repointing
    `spec.source.path` to `docs`, which holds no manifest at all, kept all
    seven tests green: the suite emptied itself in exactly the situation it
    exists to catch, since the original P0 *was* ArgoCD syncing a path that
    carried none of the posture. `test_every_synced_path_is_checkable` below
    now refuses that, and the two paths this repo can actually be pointed at
    (a chart, or a directory of manifests) are both read.
    """
    targets = []
    for rel in _deployed_paths():
        root = REPO_ROOT / rel
        if not root.is_dir():
            targets.append((rel, {}, ""))
            continue
        if (root / "Chart.yaml").is_file():
            env = _chart_env(root)
            search = root / "templates"
        else:
            env = _plain_env(root)
            search = root
        text = "\n".join(
            f.read_text(encoding="utf-8", errors="replace") for f in sorted(search.rglob("*.yaml")) if f.is_file()
        )
        targets.append((rel, env, text))
    return targets


def test_every_synced_path_is_checkable():
    """Nothing below may pass by having found nothing to look at.

    This is the second positive control, and it exists because the first was
    not enough: `test_the_scan_finds_what_the_deployer_syncs` asserts only that
    some Application names a path and that the path is a directory. `docs`
    satisfies both and carries no manifest, so the safety assertions ran over
    an empty list and reported success.
    """
    targets = _deployed_targets()
    assert targets, "no ArgoCD Application declares a source path"
    blind = [rel for rel, env, text in targets if not env and not text.strip()]
    assert not blind, (
        f"ArgoCD syncs {blind}, from which no environment or manifest could be read. "
        "Every assertion about the deployed safety posture would pass over nothing."
    )


@pytest.mark.parametrize("key", SAFETY_KEYS)
def test_the_deployed_chart_states_each_safety_key(key):
    """Absence is the dangerous half, and here every key was absent.

    `HOPEFX_INVARIANT_MODE` unset resolves to `monitor`, so the constitutional
    invariants observe and never refuse. `DRIFT_BLOCK` unset resolves to
    `false`, so inference continues on a drifted feature distribution. Neither
    is visible in any diff, because there is no line to diff.
    """
    missing = [path for path, env, _ in _deployed_targets() if key not in env]
    assert not missing, (
        f"{key} is not declared by the chart(s) the deployer syncs: {missing}. "
        f"It falls back to a code default nobody reading the chart can see."
    )


def test_the_deployed_chart_does_not_ship_a_weakened_safety_value():
    """Stating a key is half of it; stating it at a safe value is the other."""
    weak = []
    for path, env, _ in _deployed_targets():
        mode = env.get("HOPEFX_INVARIANT_MODE", "").strip().lower()
        if mode and mode != "enforce" and not env.get("HOPEFX_INVARIANT_ENFORCE_KINDS", "").strip():
            weak.append(f"{path}: HOPEFX_INVARIANT_MODE={mode} enforces no kinds")
        for key in ("DRIFT_BLOCK", "STALE_MODEL_BLOCK"):
            value = env.get(key)
            if value is not None and value.strip().lower() != "true":
                weak.append(f"{path}: {key}={value}")
    assert not weak, "the deployed chart ships a weakened safety value:\n  " + "\n  ".join(weak)


def test_the_deployed_chart_gives_the_kill_switch_layer_five():
    """Layer 5 needs an object to patch, and the chart shipped none.

    Worse than absent: `syncPolicy.automated.prune: true` means ArgoCD deletes a
    kill-switch ConfigMap applied out-of-band from `k8s/`, because the chart does
    not declare it. Applying `k8s/` by hand does not survive the next sync.
    """
    missing = []
    for path, _, rendered in _deployed_targets():
        if KILL_SWITCH_CONFIGMAP not in rendered:
            missing.append(f"{path}: no template declares the {KILL_SWITCH_CONFIGMAP} ConfigMap")
    assert not missing, "the deployed chart omits the kill switch's Redis-outage fallback:\n  " + "\n  ".join(missing)


def test_the_deployed_chart_grants_rbac_for_the_kill_switch():
    """An object the pod cannot read or patch is the same as no object.

    The `deployments/k8s/` set failed on exactly this (F139): the ConfigMap was
    there, and pods ran as the namespace `default` ServiceAccount that no
    RoleBinding named, so every get/patch was refused.
    """
    problems = []
    for path, _, rendered in _deployed_targets():
        if "kind: Role" not in rendered or "kind: RoleBinding" not in rendered:
            problems.append(f"{path}: no Role/RoleBinding for the kill-switch ConfigMap")
        if "kind: ServiceAccount" not in rendered:
            problems.append(f"{path}: no ServiceAccount")
        if "serviceAccountName:" not in rendered:
            problems.append(f"{path}: the Deployment names no ServiceAccount, so pods run as `default`")
    assert not problems, "the deployed chart cannot reach the kill-switch ConfigMap:\n  " + "\n  ".join(problems)
