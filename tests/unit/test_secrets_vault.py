# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_secrets_vault.py
================================
`core/secrets_vault.py` — 408 statements, previously 0% covered.

This is the module every broker credential, database password and JWT secret
passes through in a Vault or AWS deployment, and nothing exercised it. The
consequences of a bug here are quiet ones: a cache that serves a rotated-away
credential, a fallback that silently downgrades a production Vault deployment
to reading environment variables, an audit log that grows without bound.

The provider backends are faked at the `hvac` / `boto3` boundary rather than
mocked at the method level, so the tests cover the real call shapes — KV v2
paths, AppRole login, the AWS create-then-put upsert, the paginator — and would
catch a change to any of them.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import time
import types

import pytest

pytestmark = pytest.mark.unit


# ── Fakes ─────────────────────────────────────────────────────────────────────


class _FakeKvV2:
    """Stands in for hvac's `client.secrets.kv.v2`."""

    def __init__(self, store: dict, fail: bool = False) -> None:
        self._store = store
        self._fail = fail
        self.calls: list[tuple] = []

    def read_secret_version(self, path: str, mount_point: str):
        self.calls.append(("read", path, mount_point))
        if self._fail:
            raise RuntimeError("vault unreachable")
        if path not in self._store:
            raise KeyError(path)
        return {"data": {"data": self._store[path]}}

    def create_or_update_secret(self, path: str, secret: dict, mount_point: str):
        self.calls.append(("write", path, mount_point))
        if self._fail:
            raise RuntimeError("vault unreachable")
        self._store[path] = secret

    def delete_metadata_and_all_versions(self, path: str, mount_point: str):
        self.calls.append(("delete", path, mount_point))
        if self._fail:
            raise RuntimeError("vault unreachable")
        self._store.pop(path, None)

    def list_secrets(self, path: str, mount_point: str):
        self.calls.append(("list", path, mount_point))
        if self._fail:
            raise RuntimeError("vault unreachable")
        return {"data": {"keys": sorted(k.split("/")[-1] for k in self._store)}}


def _install_fake_hvac(monkeypatch, *, store=None, authenticated=True, fail=False, approle_token=None):
    """Register a fake `hvac` module and return the client instance it hands out."""
    kv = _FakeKvV2(store if store is not None else {}, fail=fail)

    class _FakeClient:
        def __init__(self, url: str) -> None:
            self.url = url
            self.token = ""
            self.secrets = types.SimpleNamespace(kv=types.SimpleNamespace(v2=kv))
            self.auth = types.SimpleNamespace(
                approle=types.SimpleNamespace(
                    login=lambda role_id, secret_id: {"auth": {"client_token": approle_token or "approle-tok"}}
                )
            )

        def is_authenticated(self) -> bool:
            return authenticated

    made: list = []

    def _client_factory(url):
        c = _FakeClient(url)
        made.append(c)
        return c

    monkeypatch.setitem(sys.modules, "hvac", types.SimpleNamespace(Client=_client_factory))
    return kv, made


class _AwsNotFound(Exception):
    pass


class _AwsExists(Exception):
    pass


class _FakeAwsClient:
    def __init__(self, store: dict) -> None:
        self._store = store
        self.exceptions = types.SimpleNamespace(
            ResourceNotFoundException=_AwsNotFound,
            ResourceExistsException=_AwsExists,
        )
        self.calls: list[tuple] = []

    def get_secret_value(self, SecretId: str):
        self.calls.append(("get", SecretId))
        if SecretId not in self._store:
            raise _AwsNotFound(SecretId)
        return {"SecretString": self._store[SecretId]}

    def create_secret(self, Name: str, SecretString: str):
        self.calls.append(("create", Name))
        if Name in self._store:
            raise _AwsExists(Name)
        self._store[Name] = SecretString

    def put_secret_value(self, SecretId: str, SecretString: str):
        self.calls.append(("put", SecretId))
        self._store[SecretId] = SecretString

    def delete_secret(self, SecretId: str, ForceDeleteWithoutRecovery: bool):
        self.calls.append(("delete", SecretId))
        self._store.pop(SecretId, None)

    def get_paginator(self, name: str):
        store = self._store

        class _Paginator:
            def paginate(self, Filters):
                yield {"SecretList": [{"Name": n} for n in sorted(store)]}

        return _Paginator()


def _install_fake_boto3(monkeypatch, store=None, raise_on_client=None):
    client = _FakeAwsClient(store if store is not None else {})

    def _factory(service, region_name):
        if raise_on_client:
            raise raise_on_client
        return client

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=_factory))
    return client


# ── CachedSecret ──────────────────────────────────────────────────────────────


def test_a_cached_secret_expires_once_its_ttl_has_passed():
    from core.secrets_vault import CachedSecret

    fresh = CachedSecret(key="k", value="v", fetched_at=time.time(), ttl=300)
    stale = CachedSecret(key="k", value="v", fetched_at=time.time() - 301, ttl=300)

    assert fresh.is_expired is False
    assert stale.is_expired is True


def test_a_zero_ttl_secret_is_expired_immediately():
    """A rotated-away credential must not be served from cache."""
    from core.secrets_vault import CachedSecret

    assert CachedSecret(key="k", value="v", fetched_at=time.time() - 0.01, ttl=0).is_expired is True


def test_secret_metadata_defaults_are_inert():
    from core.secrets_vault import SecretMetadata

    m = SecretMetadata(key="broker_api_key", version="3")

    assert m.rotation_enabled is False
    assert m.created_at is None and m.expires_at is None and m.last_rotated is None


# ── EnvironmentProvider ───────────────────────────────────────────────────────


async def test_the_env_provider_maps_key_names_to_env_var_names(monkeypatch):
    """ "broker.api-key" -> BROKER_API_KEY. Dots and dashes both become underscores."""
    from core.secrets_vault import EnvironmentProvider

    monkeypatch.setenv("BROKER_API_KEY", "secret-value")
    p = EnvironmentProvider()

    assert await p.initialize() is True
    assert p.provider_name == "env"
    assert await p.get_secret("broker.api-key") == "secret-value"
    assert await p.get_secret("broker_api_key") == "secret-value"


async def test_the_env_provider_returns_none_for_an_unset_key(monkeypatch):
    from core.secrets_vault import EnvironmentProvider

    monkeypatch.delenv("DEFINITELY_NOT_SET_XYZ", raising=False)

    assert await EnvironmentProvider().get_secret("definitely_not_set_xyz") is None


async def test_the_env_provider_groups_by_prefix_and_strips_it(monkeypatch):
    from core.secrets_vault import EnvironmentProvider

    monkeypatch.setenv("BROKER_API_KEY", "k")
    monkeypatch.setenv("BROKER_API_SECRET", "s")
    monkeypatch.setenv("UNRELATED_THING", "no")

    group = await EnvironmentProvider().get_secret_group("broker")

    assert group["api_key"] == "k"
    assert group["api_secret"] == "s"
    assert "unrelated_thing" not in group


async def test_the_env_provider_round_trips_set_and_delete(monkeypatch):
    import os

    from core.secrets_vault import EnvironmentProvider

    p = EnvironmentProvider()
    monkeypatch.delenv("ROUNDTRIP_KEY", raising=False)

    assert await p.set_secret("roundtrip.key", "v1") is True
    assert os.environ["ROUNDTRIP_KEY"] == "v1"
    assert await p.get_secret("roundtrip.key") == "v1"

    assert await p.delete_secret("roundtrip.key") is True
    assert await p.get_secret("roundtrip.key") is None
    # Deleting again is not an error.
    assert await p.delete_secret("roundtrip.key") is True


async def test_the_env_provider_lists_only_hopefx_prefixed_keys(monkeypatch):
    from core.secrets_vault import EnvironmentProvider

    monkeypatch.setenv("HOPEFX_ONE", "1")
    monkeypatch.setenv("NOT_HOPEFX_TWO", "2")

    keys = await EnvironmentProvider().list_secrets()

    assert "HOPEFX_ONE" in keys
    assert "NOT_HOPEFX_TWO" not in keys


# ── VaultProvider ─────────────────────────────────────────────────────────────


async def test_vault_authenticates_with_a_static_token(monkeypatch):
    import core.secrets_vault as sv

    monkeypatch.setattr(sv, "_VAULT_ROLE_ID", "")
    monkeypatch.setattr(sv, "_VAULT_SECRET_ID", "")
    _install_fake_hvac(monkeypatch)

    p = sv.VaultProvider()
    p._token = "static-token"

    assert await p.initialize() is True
    assert p.provider_name == "vault"


async def test_vault_prefers_approle_and_stores_the_issued_token(monkeypatch):
    import core.secrets_vault as sv

    monkeypatch.setattr(sv, "_VAULT_ROLE_ID", "role")
    monkeypatch.setattr(sv, "_VAULT_SECRET_ID", "sid")
    _, made = _install_fake_hvac(monkeypatch, approle_token="issued-by-approle")

    p = sv.VaultProvider()
    p._token = "would-be-ignored"

    assert await p.initialize() is True
    assert p._token == "issued-by-approle"
    assert made[0].token == "issued-by-approle"


async def test_vault_refuses_to_initialise_with_no_auth_configured(monkeypatch):
    """Failing closed matters: the fallback downgrades production to env vars."""
    import core.secrets_vault as sv

    monkeypatch.setattr(sv, "_VAULT_ROLE_ID", "")
    monkeypatch.setattr(sv, "_VAULT_SECRET_ID", "")
    _install_fake_hvac(monkeypatch)

    p = sv.VaultProvider()
    p._token = ""

    assert await p.initialize() is False


async def test_vault_reports_failure_when_the_server_rejects_the_token(monkeypatch):
    import core.secrets_vault as sv

    monkeypatch.setattr(sv, "_VAULT_ROLE_ID", "")
    monkeypatch.setattr(sv, "_VAULT_SECRET_ID", "")
    _install_fake_hvac(monkeypatch, authenticated=False)

    p = sv.VaultProvider()
    p._token = "bad-token"

    assert await p.initialize() is False


async def test_vault_reports_failure_when_hvac_is_not_installed(monkeypatch):
    import core.secrets_vault as sv

    monkeypatch.setitem(sys.modules, "hvac", None)  # import hvac -> ImportError

    assert await sv.VaultProvider().initialize() is False


async def test_an_unauthenticated_vault_provider_serves_nothing(monkeypatch):
    """Every accessor must fail closed rather than raise or return junk."""
    import core.secrets_vault as sv

    p = sv.VaultProvider()  # never initialised

    assert await p.get_secret("k") is None
    assert await p.get_secret_group("g") == {}
    assert await p.set_secret("k", "v") is False
    assert await p.delete_secret("k") is False
    assert await p.list_secrets() == []


async def _vault_ready(monkeypatch, store=None, fail=False):
    import core.secrets_vault as sv

    monkeypatch.setattr(sv, "_VAULT_ROLE_ID", "")
    monkeypatch.setattr(sv, "_VAULT_SECRET_ID", "")
    kv, _ = _install_fake_hvac(monkeypatch, store=store, fail=fail)
    p = sv.VaultProvider()
    p._token = "tok"
    await p.initialize()
    return p, kv, sv


async def test_vault_reads_the_value_key_from_kv_v2(monkeypatch):
    p, kv, sv = await _vault_ready(
        monkeypatch,
        store={f"{__import__('core.secrets_vault', fromlist=['x'])._VAULT_PREFIX}/api_key": {"value": "sekrit"}},
    )

    assert await p.get_secret("api_key") == "sekrit"
    assert kv.calls[0][0] == "read"


async def test_vault_falls_back_to_the_key_name_when_there_is_no_value_field(monkeypatch):
    import core.secrets_vault as sv

    store = {f"{sv._VAULT_PREFIX}/api_key": {"api_key": "by-name"}}  # pragma: allowlist secret
    p, _, _ = await _vault_ready(monkeypatch, store=store)

    assert await p.get_secret("api_key") == "by-name"


async def test_vault_returns_none_when_the_read_fails(monkeypatch):
    p, _, _ = await _vault_ready(monkeypatch, fail=True)

    assert await p.get_secret("anything") is None


async def test_vault_group_read_returns_the_whole_data_map(monkeypatch):
    import core.secrets_vault as sv

    p, _, _ = await _vault_ready(monkeypatch, store={f"{sv._VAULT_PREFIX}/broker": {"api_key": "k", "api_secret": "s"}})

    assert await p.get_secret_group("broker") == {"api_key": "k", "api_secret": "s"}


async def test_vault_group_read_returns_empty_on_failure(monkeypatch):
    p, _, _ = await _vault_ready(monkeypatch, fail=True)

    assert await p.get_secret_group("broker") == {}


async def test_vault_write_then_read_round_trips(monkeypatch):
    import core.secrets_vault as sv

    store: dict = {}
    p, _, _ = await _vault_ready(monkeypatch, store=store)

    assert await p.set_secret("new_key", "new_value") is True
    assert store[f"{sv._VAULT_PREFIX}/new_key"] == {"value": "new_value"}
    assert await p.get_secret("new_key") == "new_value"


async def test_vault_write_reports_failure(monkeypatch):
    p, _, _ = await _vault_ready(monkeypatch, fail=True)

    assert await p.set_secret("k", "v") is False


async def test_vault_delete_removes_all_versions(monkeypatch):
    import core.secrets_vault as sv

    store = {f"{sv._VAULT_PREFIX}/gone": {"value": "x"}}
    p, _, _ = await _vault_ready(monkeypatch, store=store)

    assert await p.delete_secret("gone") is True
    assert store == {}


async def test_vault_delete_reports_failure(monkeypatch):
    p, _, _ = await _vault_ready(monkeypatch, fail=True)

    assert await p.delete_secret("k") is False


async def test_vault_lists_keys(monkeypatch):
    import core.secrets_vault as sv

    p, _, _ = await _vault_ready(
        monkeypatch, store={f"{sv._VAULT_PREFIX}/a": {"value": "1"}, f"{sv._VAULT_PREFIX}/b": {"value": "2"}}
    )

    assert await p.list_secrets() == ["a", "b"]


async def test_vault_list_returns_empty_on_failure(monkeypatch):
    p, _, _ = await _vault_ready(monkeypatch, fail=True)

    assert await p.list_secrets() == []


async def test_closing_vault_drops_the_client_and_the_auth_flag(monkeypatch):
    p, _, _ = await _vault_ready(monkeypatch)

    await p.close()

    assert p._client is None
    assert p._authenticated is False
    # Accessors fail closed afterwards.
    assert await p.get_secret("k") is None


# ── AWSSecretsProvider ────────────────────────────────────────────────────────


async def test_aws_initialises_a_secretsmanager_client(monkeypatch):
    from core.secrets_vault import AWSSecretsProvider

    _install_fake_boto3(monkeypatch)
    p = AWSSecretsProvider()

    assert await p.initialize() is True
    assert p.provider_name == "aws"


async def test_aws_reports_failure_when_boto3_is_not_installed(monkeypatch):
    from core.secrets_vault import AWSSecretsProvider

    monkeypatch.setitem(sys.modules, "boto3", None)

    assert await AWSSecretsProvider().initialize() is False


async def test_aws_reports_failure_when_the_client_cannot_be_built(monkeypatch):
    from core.secrets_vault import AWSSecretsProvider

    _install_fake_boto3(monkeypatch, raise_on_client=RuntimeError("no credentials"))

    assert await AWSSecretsProvider().initialize() is False


async def test_an_uninitialised_aws_provider_serves_nothing():
    from core.secrets_vault import AWSSecretsProvider

    p = AWSSecretsProvider()

    assert await p.get_secret("k") is None
    assert await p.get_secret_group("g") == {}
    assert await p.set_secret("k", "v") is False
    assert await p.delete_secret("k") is False
    assert await p.list_secrets() == []


async def _aws_ready(monkeypatch, store=None):
    import core.secrets_vault as sv

    client = _install_fake_boto3(monkeypatch, store=store)
    p = sv.AWSSecretsProvider()
    await p.initialize()
    return p, client, sv


async def test_aws_unwraps_the_value_field_of_a_json_secret(monkeypatch):
    import core.secrets_vault as sv

    p, _, _ = await _aws_ready(monkeypatch, store={f"{sv._AWS_PREFIX}api_key": json.dumps({"value": "sekrit"})})

    assert await p.get_secret("api_key") == "sekrit"


async def test_aws_returns_the_raw_string_when_it_is_not_json(monkeypatch):
    import core.secrets_vault as sv

    store = {f"{sv._AWS_PREFIX}api_key": "plain-not-json"}  # pragma: allowlist secret
    p, _, _ = await _aws_ready(monkeypatch, store=store)

    assert await p.get_secret("api_key") == "plain-not-json"


async def test_aws_returns_none_for_a_missing_secret(monkeypatch):
    p, _, _ = await _aws_ready(monkeypatch, store={})

    assert await p.get_secret("nope") is None


async def test_aws_group_read_returns_the_parsed_json_map(monkeypatch):
    import core.secrets_vault as sv

    p, _, _ = await _aws_ready(
        monkeypatch, store={f"{sv._AWS_PREFIX}broker": json.dumps({"api_key": "k", "api_secret": "s"})}
    )

    assert await p.get_secret_group("broker") == {"api_key": "k", "api_secret": "s"}


async def test_aws_group_read_returns_empty_when_absent(monkeypatch):
    p, _, _ = await _aws_ready(monkeypatch, store={})

    assert await p.get_secret_group("broker") == {}


async def test_aws_set_creates_a_new_secret(monkeypatch):
    import core.secrets_vault as sv

    store: dict = {}
    p, client, _ = await _aws_ready(monkeypatch, store=store)

    assert await p.set_secret("fresh", "v") is True
    assert json.loads(store[f"{sv._AWS_PREFIX}fresh"]) == {"value": "v"}
    assert ("create", f"{sv._AWS_PREFIX}fresh") in client.calls


async def test_aws_set_falls_back_to_put_when_the_secret_already_exists(monkeypatch):
    """The create-then-put upsert — the branch a plain create would never reach."""
    import core.secrets_vault as sv

    store = {f"{sv._AWS_PREFIX}existing": json.dumps({"value": "old"})}
    p, client, _ = await _aws_ready(monkeypatch, store=store)

    assert await p.set_secret("existing", "new") is True
    assert json.loads(store[f"{sv._AWS_PREFIX}existing"]) == {"value": "new"}
    assert ("put", f"{sv._AWS_PREFIX}existing") in client.calls


async def test_aws_delete_removes_the_secret(monkeypatch):
    import core.secrets_vault as sv

    store = {f"{sv._AWS_PREFIX}gone": "x"}
    p, _, _ = await _aws_ready(monkeypatch, store=store)

    assert await p.delete_secret("gone") is True
    assert store == {}


async def test_aws_list_strips_the_configured_prefix(monkeypatch):
    import core.secrets_vault as sv

    p, _, _ = await _aws_ready(monkeypatch, store={f"{sv._AWS_PREFIX}alpha": "1", f"{sv._AWS_PREFIX}beta": "2"})

    assert sorted(await p.list_secrets()) == ["alpha", "beta"]


async def test_closing_aws_drops_the_client(monkeypatch):
    p, _, _ = await _aws_ready(monkeypatch)

    await p.close()

    assert p._client is None
    assert await p.get_secret("k") is None


# ── SecretsManager ────────────────────────────────────────────────────────────


async def _manager(monkeypatch, provider="env"):
    import core.secrets_vault as sv

    monkeypatch.setattr(sv, "_PROVIDER", provider)
    m = sv.SecretsManager()
    await m.initialize()
    return m, sv


async def test_an_uninitialised_manager_reports_no_provider():
    from core.secrets_vault import SecretsManager

    m = SecretsManager()

    assert m.provider_name == "none"
    assert m.is_initialized is False


async def test_an_uninitialised_manager_serves_nothing():
    """Every accessor guards on `_initialized` — none may raise."""
    from core.secrets_vault import SecretsManager

    m = SecretsManager()

    assert await m.get("k") is None
    assert await m.get_group("g") == {}
    assert await m.set("k", "v") is False
    assert await m.delete("k") is False
    assert await m.list_keys() == []


async def test_the_manager_selects_the_env_provider_by_default(monkeypatch):
    m, _ = await _manager(monkeypatch, provider="env")

    assert m.is_initialized is True
    assert m.provider_name == "env"


async def test_the_manager_selects_vault_when_configured(monkeypatch):
    import core.secrets_vault as sv

    monkeypatch.setattr(sv, "_VAULT_ROLE_ID", "")
    monkeypatch.setattr(sv, "_VAULT_SECRET_ID", "")
    monkeypatch.setattr(sv, "_VAULT_TOKEN", "tok")
    _install_fake_hvac(monkeypatch)
    monkeypatch.setattr(sv, "_PROVIDER", "vault")

    m = sv.SecretsManager()
    await m.initialize()

    assert m.provider_name == "vault"
    await m.close()


async def test_the_manager_selects_aws_when_configured(monkeypatch):
    import core.secrets_vault as sv

    _install_fake_boto3(monkeypatch)
    monkeypatch.setattr(sv, "_PROVIDER", "aws")

    m = sv.SecretsManager()
    await m.initialize()

    assert m.provider_name == "aws"
    await m.close()


async def test_a_failed_primary_provider_falls_back_to_env(monkeypatch):
    """Worth pinning: this silently downgrades a production Vault deployment."""
    import core.secrets_vault as sv

    monkeypatch.setattr(sv, "_PROVIDER", "vault")
    monkeypatch.setitem(sys.modules, "hvac", None)  # initialize() -> False

    m = sv.SecretsManager()

    assert await m.initialize() is True
    assert m.provider_name == "env", "the fallback did not engage"
    await m.close()


async def test_the_manager_caches_a_fetched_secret(monkeypatch):
    m, sv = await _manager(monkeypatch)
    monkeypatch.setenv("CACHED_KEY", "first")

    assert await m.get("cached_key") == "first"

    # Change the underlying value; the cache must still answer.
    monkeypatch.setenv("CACHED_KEY", "second")
    assert await m.get("cached_key") == "first"

    # ...and use_cache=False must go back to the provider.
    assert await m.get("cached_key", use_cache=False) == "second"


async def test_an_expired_cache_entry_is_refetched(monkeypatch):
    m, sv = await _manager(monkeypatch)
    monkeypatch.setattr(sv, "_CACHE_TTL", 0)
    monkeypatch.setenv("TTL_KEY", "one")

    assert await m.get("ttl_key") == "one"
    monkeypatch.setenv("TTL_KEY", "two")
    time.sleep(0.01)

    assert await m.get("ttl_key") == "two"


async def test_a_missing_secret_is_not_cached(monkeypatch):
    m, _ = await _manager(monkeypatch)
    monkeypatch.delenv("LATER_KEY", raising=False)

    assert await m.get("later_key") is None

    monkeypatch.setenv("LATER_KEY", "now-set")
    assert await m.get("later_key") == "now-set", "a None result was cached"


async def test_setting_a_secret_invalidates_its_cache_entry(monkeypatch):
    """Otherwise a rotation is invisible until the TTL lapses."""
    m, _ = await _manager(monkeypatch)
    monkeypatch.setenv("ROTATE_ME", "old")

    assert await m.get("rotate_me") == "old"
    assert await m.set("rotate_me", "new") is True
    assert await m.get("rotate_me") == "new"


async def test_deleting_a_secret_invalidates_its_cache_entry(monkeypatch):
    m, _ = await _manager(monkeypatch)
    monkeypatch.setenv("DELETE_ME", "v")

    assert await m.get("delete_me") == "v"
    assert await m.delete("delete_me") is True
    assert await m.get("delete_me") is None


async def test_invalidate_cache_clears_one_key_or_all(monkeypatch):
    m, _ = await _manager(monkeypatch)
    monkeypatch.setenv("K_ONE", "1")
    monkeypatch.setenv("K_TWO", "2")
    await m.get("k_one")
    await m.get("k_two")
    assert m.health()["cached_secrets"] == 2

    m.invalidate_cache("k_one")
    assert m.health()["cached_secrets"] == 1

    m.invalidate_cache()
    assert m.health()["cached_secrets"] == 0


async def test_get_group_delegates_and_is_audited(monkeypatch):
    m, _ = await _manager(monkeypatch)
    monkeypatch.setenv("GRP_ALPHA", "a")

    assert await m.get_group("grp") == {"alpha": "a"}
    assert any(e["operation"] == "get_group" for e in m._access_log)


async def test_list_keys_delegates_to_the_provider(monkeypatch):
    m, _ = await _manager(monkeypatch)
    monkeypatch.setenv("HOPEFX_LISTED", "x")

    assert "HOPEFX_LISTED" in await m.list_keys()


async def test_health_reports_cache_and_audit_sizes(monkeypatch):
    m, sv = await _manager(monkeypatch)
    monkeypatch.setenv("HEALTH_KEY", "v")
    await m.get("health_key")

    h = m.health()

    assert h["initialized"] is True
    assert h["provider"] == "env"
    assert h["cached_secrets"] == 1
    assert h["expired_cached"] == 0
    assert h["access_log_size"] >= 1


async def test_health_counts_expired_entries_separately(monkeypatch):
    from core.secrets_vault import CachedSecret

    m, _ = await _manager(monkeypatch)
    m._cache["stale"] = CachedSecret(key="stale", value="v", fetched_at=time.time() - 999, ttl=1)

    h = m.health()

    assert h["cached_secrets"] == 1
    assert h["expired_cached"] == 1


async def test_every_access_is_audit_logged_with_its_outcome(monkeypatch):
    """Compliance depends on this: cache_hit, fetched and not_found are distinct."""
    m, _ = await _manager(monkeypatch)
    monkeypatch.setenv("AUDITED", "v")
    monkeypatch.delenv("ABSENT_KEY", raising=False)

    await m.get("audited")  # fetched
    await m.get("audited")  # cache_hit
    await m.get("absent_key")  # not_found

    results = [e["result"] for e in m._access_log]
    assert "fetched" in results
    assert "cache_hit" in results
    assert "not_found" in results
    assert all(e["provider"] == "env" for e in m._access_log)


async def test_the_audit_log_is_bounded_and_keeps_the_most_recent(monkeypatch):
    """An unbounded in-memory log is a slow leak in a long-running process."""
    m, _ = await _manager(monkeypatch)

    for i in range(10_050):
        m._audit_log("get", f"key_{i}", "fetched")

    log = m._access_log
    assert len(log) <= 10_000
    assert log[-1]["key"] == "key_10049", "the trim dropped the newest entries"


async def test_closing_the_manager_marks_it_uninitialised(monkeypatch):
    m, _ = await _manager(monkeypatch)

    await m.close()

    assert m.is_initialized is False
    assert await m.get("anything") is None


async def test_closing_cancels_the_rotation_task(monkeypatch):
    """Left running, it holds a reference to the provider after shutdown."""
    import core.secrets_vault as sv

    monkeypatch.setattr(sv, "_VAULT_ROLE_ID", "")
    monkeypatch.setattr(sv, "_VAULT_SECRET_ID", "")
    monkeypatch.setattr(sv, "_VAULT_TOKEN", "tok")
    monkeypatch.setattr(sv, "_PROVIDER", "vault")
    monkeypatch.setattr(sv, "_ROTATION_CHECK", 3600)
    _install_fake_hvac(monkeypatch)

    m = sv.SecretsManager()
    await m.initialize()
    task = m._rotation_task
    assert task is not None, "no rotation task was started for a non-env provider"

    await m.close()

    assert task.cancelled() or task.done()


async def test_no_rotation_task_is_started_for_the_env_provider(monkeypatch):
    m, _ = await _manager(monkeypatch, provider="env")

    assert m._rotation_task is None
    await m.close()


async def test_the_rotation_loop_refreshes_expired_entries(monkeypatch):
    import core.secrets_vault as sv

    from core.secrets_vault import CachedSecret

    monkeypatch.setattr(sv, "_ROTATION_CHECK", 0)
    monkeypatch.setattr(sv, "_CACHE_TTL", 300)
    m, _ = await _manager(monkeypatch, provider="env")
    monkeypatch.setenv("ROTATING", "new-value")

    m._cache["rotating"] = CachedSecret(key="rotating", value="old-value", fetched_at=0.0, ttl=1)

    task = asyncio.create_task(m._rotation_loop())
    for _ in range(50):
        await asyncio.sleep(0.01)
        if m._cache["rotating"].value == "new-value":
            break
    task.cancel()
    # The loop catches CancelledError and breaks, so the task finishes normally
    # rather than propagating — suppressing here rather than asserting a raise.
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert m._cache["rotating"].value == "new-value"


async def test_the_rotation_loop_survives_a_provider_error(monkeypatch):
    """A refresh failure must not kill the loop and stop all future rotation."""
    import core.secrets_vault as sv

    from core.secrets_vault import CachedSecret

    monkeypatch.setattr(sv, "_ROTATION_CHECK", 0)
    m, _ = await _manager(monkeypatch, provider="env")

    class _Boom:
        async def get_secret(self, key):
            raise RuntimeError("provider down")

    m._provider = _Boom()
    m._cache["k"] = CachedSecret(key="k", value="v", fetched_at=0.0, ttl=1)

    task = asyncio.create_task(m._rotation_loop())
    await asyncio.sleep(0.05)

    assert not task.done(), "the loop died on a provider error"
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


# ── Singleton ─────────────────────────────────────────────────────────────────


def test_get_secrets_manager_returns_the_same_instance(monkeypatch):
    import core.secrets_vault as sv

    monkeypatch.setattr(sv, "_manager", None)

    first = sv.get_secrets_manager()
    second = sv.get_secrets_manager()

    assert first is second
    assert isinstance(first, sv.SecretsManager)
