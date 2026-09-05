# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Two ConfigMaps share a name. They must not disagree about safety.

`k8s/k8s-configmap.yaml` and `deployments/k8s/configmap.yaml` both declare

    kind: ConfigMap
    metadata:
      name: hopefx-config
      namespace: hopefx

and both Deployments mount it with `envFrom: configMapRef: hopefx-config`.
`kubectl apply` **replaces `data` wholesale**, so whichever file was applied last
defines the safety posture for both deployments — and they disagree (F98/F178):

| Key | `k8s/` | `deployments/k8s/` |
|---|---|---|
| `HOPEFX_INVARIANT_MODE` | `enforce` | `monitor` |
| `DRIFT_BLOCK` | `true` | **absent** |
| `STALE_MODEL_BLOCK` | `true` | **absent** |
| `OANDA_PRACTICE` | `false` (real money) | absent |
| `BROKER_TYPE` | `oanda` | absent |

Absence is the dangerous half. A key that is *present and weaker* is at least
visible in a diff; a key that is **missing** silently falls back to a code
default, and `DRIFT_BLOCK` defaults to `false` (`ml/inference_engine.py`) — so
applying the second file last leaves the platform trading on drifted models with
real-money OANDA credentials, while the sibling file's own comment declares that
exact combination CRITICAL.

These tests do not force the two files to be identical. Broker selection is a
deployment choice and may legitimately differ. What may not differ is the
safety posture: every key that weakens a control when absent or downgraded must
be **stated explicitly in every file**, at a value no weaker than the strictest
sibling.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_DIRS = ("k8s", "deployments/k8s")

# The application-configuration ConfigMap. Scoped by name on purpose: other
# ConfigMaps legitimately share a name across the two manifest sets without
# carrying any of these keys — `hopefx-kill-switch` is cross-pod *state*, not
# configuration, and requiring DRIFT_BLOCK of it would be a false positive.
CONFIG_MAP_NAME = "hopefx-config"

# Keys whose absence or downgrade weakens a control.
SAFETY_KEYS: tuple[str, ...] = (
    "HOPEFX_INVARIANT_MODE",
    "DRIFT_BLOCK",
    "STALE_MODEL_BLOCK",
)


def _configmaps() -> dict[str, list[tuple[str, dict]]]:
    """Every ConfigMap in every manifest set, keyed by metadata name."""
    import yaml

    found: dict[str, list[tuple[str, dict]]] = {}
    for directory in MANIFEST_DIRS:
        base = REPO_ROOT / directory
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.yaml")):
            for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
                if not isinstance(doc, dict) or doc.get("kind") != "ConfigMap":
                    continue
                name = (doc.get("metadata") or {}).get("name")
                if name:
                    found.setdefault(name, []).append((f"{directory}/{path.name}", doc))
    return found


def test_the_scan_finds_the_configmaps():
    """A scan that matches nothing agrees with every assertion below."""
    found = _configmaps()
    assert found, "no ConfigMaps found in any manifest set — the scan pattern is wrong"
    total = sum(len(docs) for docs in found.values())
    assert total >= 3, f"only {total} ConfigMap documents found across {MANIFEST_DIRS}"


def test_no_configmap_name_is_declared_in_two_manifest_sets():
    """The structural fix, and the thing that must not regress.

    `kubectl apply` replaces a ConfigMap's `data` wholesale. Two files declaring
    one name in one namespace therefore means whichever was applied last defines
    that configuration for **every** deployment mounting it — silently.

    `hopefx-config` was declared by both `k8s/k8s-configmap.yaml` and
    `deployments/k8s/configmap.yaml`, and they disagreed on enforcement mode, on
    both ML safety blocks (absent in one, so falling back to a code default of
    *false* for DRIFT_BLOCK), and on enforcement scope and fail-closed behaviour
    (F98/F178/F265).

    The two sets have genuinely different intents — one runs full enforcement
    against a live broker, the other the documented staged rollout — so the fix
    is separate names, not a forced merge that would have made an operational
    decision belonging to whoever owns the cluster.

    Sharing a name is not itself the defect — `hopefx-kill-switch` is declared in
    both sets on purpose, because it is one cross-pod *state* object that both
    deployments read by that exact name and whose RBAC grants it by name. Its
    `data` is byte-identical in both files, so apply order changes nothing.

    Divergent data under a shared name is the defect.
    """
    import json

    collisions = {}
    for name, docs in _configmaps().items():
        if len({filename.split("/")[0] for filename, _doc in docs}) < 2:
            continue
        rendered = {filename: json.dumps(doc.get("data") or {}, sort_keys=True) for filename, doc in docs}
        if len(set(rendered.values())) > 1:
            collisions[name] = sorted(rendered)

    assert not collisions, (
        "a ConfigMap name is declared in more than one manifest set with DIFFERENT data, "
        "so `kubectl apply` order decides its contents:\n  "
        + "\n  ".join(f"{name}: {files}" for name, files in collisions.items())
    )


@pytest.mark.parametrize("key", SAFETY_KEYS)
def test_every_application_configmap_states_each_safety_key(key):
    """Absence is the dangerous half: a missing key falls back to a code default
    that nobody reading the manifest can see, and `DRIFT_BLOCK` defaults to
    **false**. Applied to any ConfigMap that configures the application — that is,
    any that already carries an invariant setting."""
    missing = []
    for name, docs in _configmaps().items():
        for filename, doc in docs:
            data = doc.get("data") or {}
            if "HOPEFX_INVARIANT_MODE" not in data:
                continue  # not an application-configuration ConfigMap
            if key not in data:
                missing.append(f"{filename} (ConfigMap {name})")

    assert not missing, (
        f"{key} is absent from an application ConfigMap, so the code default decides it "
        f"silently:\n  " + "\n  ".join(missing)
    )


def test_the_drift_and_stale_blocks_are_on_wherever_they_are_declared():
    """`DRIFT_BLOCK` defaults to false in code. A manifest that ships it off is
    making a real-money decision in a file nobody diffs."""
    weak = []
    for name, docs in _configmaps().items():
        for filename, doc in docs:
            data = doc.get("data") or {}
            for key in ("DRIFT_BLOCK", "STALE_MODEL_BLOCK"):
                value = data.get(key)
                if value is not None and str(value).strip().lower() != "true":
                    weak.append(f"{filename} (ConfigMap {name}): {key}={value}")
    assert not weak, "an ML safety block is switched off in a shipped manifest:\n  " + "\n  ".join(weak)


def test_enforce_is_set_wherever_a_live_broker_is():
    """`k8s/k8s-configmap.yaml`'s own comment states the rule:

        CRITICAL: HOPEFX_INVARIANT_MODE must be "enforce" when BROKER_TYPE != "paper".

    A comment is not a control. This is."""
    violations = []
    for name, docs in _configmaps().items():
        for filename, doc in docs:
            data = doc.get("data") or {}
            broker = str(data.get("BROKER_TYPE", "")).strip().lower()
            mode = str(data.get("HOPEFX_INVARIANT_MODE", "")).strip().lower()
            if broker and broker != "paper" and mode != "enforce":
                violations.append(f"{filename} (ConfigMap {name}): BROKER_TYPE={broker} but mode={mode or 'unset'}")
    assert not violations, "a live broker is configured without invariant enforcement:\n  " + "\n  ".join(violations)
