# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Every shipped manifest set must give the kill switch the layers it claims.

`kill_switch.py` documents five independent activation layers precisely so no
single dependency can silence the control of last resort:

    1. in-memory flag
    2. kill_switch.flag file
    3. env var HOPEFX_KILL_SWITCH
    4. Redis latch (ks:latch)
    5. K8s ConfigMap watcher — the documented Redis-down fallback

`k8s/` grants all of them. `deployments/k8s/` — the other shipped set — silently
removes three (F139):

* **Layer 5 is denied by RBAC.** There is no RBAC manifest in that directory and
  the deployment sets no `serviceAccountName`, so pods run as the namespace
  `default` ServiceAccount, which the RoleBinding does not name. Every
  `get`/`patch` on the kill-switch ConfigMap is refused.
* **Layer 2 cannot even be written.** `_DEFAULT_FLAG_FILE` resolves to
  `/app/kill_switch.flag`, and that deployment sets `readOnlyRootFilesystem:
  true` with no volume covering `/app`. The write raises `OSError` into a
  handler that logs at WARNING. The audit recorded this as "does not survive a
  pod replacement"; it is worse — on this manifest set the file layer never
  works at all.
* **Layer 4 is explicitly optional** (`scripts/preflight.sh` downgrades an
  unreachable Redis to a warning).

Leaving layers 1 and 3: one is per-process, the other needs a redeploy to
change. An operator who hits the kill switch stops the pod they reached and no
other.

These tests read the manifests. They are cheap, they need no cluster, and they
are the only thing standing between a future edit and the same silent removal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_SETS = ("k8s", "deployments/k8s")

KILL_SWITCH_CONFIGMAP = "hopefx-kill-switch"


def _yaml_docs(directory: Path):
    """Every YAML document in a manifest directory."""
    import yaml

    docs = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
                if isinstance(doc, dict):
                    docs.append((path.name, doc))
        except yaml.YAMLError as exc:  # a manifest that will not parse cannot be applied
            pytest.fail(f"{path} is not valid YAML: {exc}")
    return docs


def _of_kind(docs, kind: str):
    return [(name, d) for name, d in docs if d.get("kind") == kind]


@pytest.fixture(params=MANIFEST_SETS, ids=MANIFEST_SETS)
def manifest_set(request):
    directory = REPO_ROOT / request.param
    if not directory.is_dir():
        pytest.skip(f"{request.param} is not present")
    return request.param, directory, _yaml_docs(directory)


# ── Layer 5: the ConfigMap watcher ───────────────────────────────────────────


def test_the_kill_switch_configmap_exists(manifest_set):
    name, _directory, docs = manifest_set
    names = {d["metadata"]["name"] for _f, d in _of_kind(docs, "ConfigMap") if d.get("metadata")}
    assert KILL_SWITCH_CONFIGMAP in names, (
        f"{name}/ ships no {KILL_SWITCH_CONFIGMAP} ConfigMap — layer 5 has nothing to watch or patch"
    )


def test_rbac_grants_access_to_the_kill_switch_configmap(manifest_set):
    name, _directory, docs = manifest_set
    roles = _of_kind(docs, "Role") + _of_kind(docs, "ClusterRole")
    assert roles, f"{name}/ defines no Role — layer 5's get/patch is denied by RBAC (F139)"

    granting = []
    for _f, role in roles:
        for rule in role.get("rules") or []:
            resources = rule.get("resources") or []
            verbs = set(rule.get("verbs") or [])
            resource_names = rule.get("resourceNames")
            names_ok = resource_names is None or KILL_SWITCH_CONFIGMAP in resource_names
            if "configmaps" in resources and {"get", "patch"} <= verbs and names_ok:
                granting.append(role["metadata"]["name"])
    assert granting, f"{name}/ has no Role granting get+patch on the {KILL_SWITCH_CONFIGMAP} ConfigMap"


def test_the_rbac_grant_is_least_privilege(manifest_set):
    """The k8s/ set scopes the Role to one ConfigMap and two verbs. A copy that
    widens that to all configmaps would pass the test above while handing the
    API pod the whole namespace's configuration."""
    _name, _directory, docs = manifest_set
    for _f, role in _of_kind(docs, "Role"):
        for rule in role.get("rules") or []:
            if "configmaps" not in (rule.get("resources") or []):
                continue
            verbs = set(rule.get("verbs") or [])
            assert "*" not in verbs, f"{role['metadata']['name']} grants all verbs on configmaps"
            assert not (verbs - {"get", "patch", "watch", "list"}), (
                f"{role['metadata']['name']} grants {sorted(verbs)} on configmaps — more than the watcher needs"
            )
            assert rule.get("resourceNames"), (
                f"{role['metadata']['name']} is not scoped with resourceNames — it covers every ConfigMap"
            )


def test_the_deployment_uses_the_service_account_the_rolebinding_names(manifest_set):
    """The RoleBinding grants to a named ServiceAccount. A deployment that does
    not set `serviceAccountName` runs as `default`, which is not that subject,
    so the grant applies to nobody."""
    name, _directory, docs = manifest_set
    deployments = _of_kind(docs, "Deployment")
    assert deployments, f"{name}/ has no Deployment"

    bound = set()
    for _f, binding in _of_kind(docs, "RoleBinding"):
        for subject in binding.get("subjects") or []:
            if subject.get("kind") == "ServiceAccount":
                bound.add(subject["name"])

    for filename, deployment in deployments:
        spec = deployment["spec"]["template"]["spec"]
        account = spec.get("serviceAccountName")
        assert account, (
            f"{name}/{filename} sets no serviceAccountName — the pod runs as 'default' "
            f"and the RoleBinding to {sorted(bound)} reaches it not at all (F139)"
        )
        assert account in bound, f"{name}/{filename} runs as {account!r}, which no RoleBinding names: {sorted(bound)}"


# ── Layer 2: the flag file ───────────────────────────────────────────────────


def test_the_flag_file_lives_on_a_writable_volume(manifest_set):
    """`readOnlyRootFilesystem: true` is correct and must stay. It means the
    flag file needs a volume: without one the write raises OSError into a
    handler that logs at WARNING, and layer 2 never works at all."""
    name, _directory, docs = manifest_set

    for filename, deployment in _of_kind(docs, "Deployment"):
        pod = deployment["spec"]["template"]["spec"]
        for container in pod.get("containers") or []:
            security = container.get("securityContext") or {}
            if not security.get("readOnlyRootFilesystem"):
                continue

            flag_path = None
            for env in container.get("env") or []:
                if env.get("name") == "KILL_SWITCH_FLAG_FILE":
                    flag_path = env.get("value")
            assert flag_path, (
                f"{name}/{filename} has a read-only root filesystem and does not set "
                "KILL_SWITCH_FLAG_FILE — the flag defaults to /app/kill_switch.flag, "
                "which cannot be written (F139)"
            )

            mounts = [m["mountPath"] for m in (container.get("volumeMounts") or [])]
            assert any(flag_path.startswith(m.rstrip("/") + "/") for m in mounts), (
                f"{name}/{filename} points KILL_SWITCH_FLAG_FILE at {flag_path}, which no volume covers: {mounts}"
            )


def test_the_kill_switch_honours_the_flag_file_environment_variable(monkeypatch, tmp_path):
    """The manifest above is only meaningful if the code reads that variable.
    Nothing in the repository set the flag path outside a test script, so an
    operator had no way to move it off the read-only image layer."""
    target = tmp_path / "state" / "kill_switch.flag"
    target.parent.mkdir()
    monkeypatch.setenv("KILL_SWITCH_FLAG_FILE", str(target))

    import kill_switch as ks_module

    # No importlib.reload: the path is resolved per construction, so setting the
    # variable is enough. Reloading here replaced the module's KillSwitch class
    # and its singleton, and three unrelated tests asserting singleton identity
    # failed for the rest of the session — the reload was the defect, not the
    # code under test.
    switch = ks_module.KillSwitch(deactivation_token="unit-test")  # nosec B106
    assert switch._flag_file == target

    monkeypatch.delenv("KILL_SWITCH_FLAG_FILE", raising=False)
    assert ks_module.KillSwitch(deactivation_token="unit-test")._flag_file != target  # nosec B106


def test_an_unwritable_flag_file_is_reported_as_a_lost_layer(monkeypatch, tmp_path, caplog):
    """Activation must still succeed — the in-memory layer is what stops trading
    in this process — but a failed write means cross-process detection is gone,
    and that is not a WARNING-level detail on the control of last resort."""
    import logging

    import kill_switch as ks_module

    unwritable = tmp_path / "no-such-dir" / "kill_switch.flag"
    switch = ks_module.KillSwitch(flag_file=unwritable, deactivation_token="unit-test")  # nosec B106

    with caplog.at_level(logging.DEBUG):
        switch.activate("drawdown breach")

    assert switch.is_active(), "activation must not depend on the flag file being writable"
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a kill-switch layer failed and nothing was logged at ERROR"
