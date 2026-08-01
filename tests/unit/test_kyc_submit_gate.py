# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_kyc_submit_gate.py
==================================
``POST /api/kyc/submit`` derives the document list from storage, and refuses a
submission that does not meet the stated requirements.

Two defects, one boundary. ``KYCPage.tsx`` has always told users it needs "at
least a government-issued ID and proof of address", and it sent
``document_types[]`` built from React state — a client-supplied claim about
which documents exist, on a compliance flow (audit #58). The server ignored
that field, which is the right call, but it also never checked that *any*
document had been stored: a submission with nothing attached was accepted,
marked ``pending``, and queued a guaranteed rejection plus a 1-2 day round trip
before the customer learned why.

The endpoint also swallowed every exception and returned ``{"success": True}``,
so a submission that was never persisted still reported success.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import TokenPayload, get_current_user

pytestmark = pytest.mark.unit

USER = "kyc-user"


@pytest.fixture
def client(monkeypatch):
    """Mount the KYC alias router over an in-memory store."""
    store: dict[str, dict] = {}

    import api.db_store as db_store

    monkeypatch.setattr(db_store, "db_get", lambda k: store.get(k))
    monkeypatch.setattr(
        db_store, "db_set", lambda k, v, **kw: store.__setitem__(k, v), raising=False
    )

    import api.kyc as kyc

    app = FastAPI()
    app.include_router(kyc.kyc_alias_router)
    app.dependency_overrides[get_current_user] = lambda: TokenPayload(sub=USER, role="user")
    return TestClient(app, raise_server_exceptions=False), store


def _docs(*types: str) -> dict:
    return {"documents": [{"type": t} for t in types]}


def test_submission_with_no_documents_is_refused(client):
    c, store = client
    store[f"kyc:{USER}"] = {"documents": []}

    res = c.post("/api/kyc/submit")

    assert res.status_code == 422, "an empty submission was accepted"
    assert "government-issued ID" in res.json()["detail"]
    assert "proof of address" in res.json()["detail"]
    assert store[f"kyc:{USER}"].get("status") != "pending", "status advanced on a refused submission"


def test_missing_record_is_refused(client):
    """No KYC record at all is the same case as no documents."""
    c, _ = client
    assert c.post("/api/kyc/submit").status_code == 422


def test_identity_document_alone_is_refused(client):
    c, store = client
    store[f"kyc:{USER}"] = _docs("passport")

    res = c.post("/api/kyc/submit")

    assert res.status_code == 422
    assert "proof of address" in res.json()["detail"]
    # The requirement that IS met must not be listed as outstanding.
    assert "government-issued ID" not in res.json()["detail"]


def test_selfie_alone_is_refused(client):
    """The original bug: one document of any type unlocked submission."""
    c, store = client
    store[f"kyc:{USER}"] = _docs("selfie")

    assert c.post("/api/kyc/submit").status_code == 422


def test_proof_of_address_alone_is_refused(client):
    c, store = client
    store[f"kyc:{USER}"] = _docs("proof_of_address")

    res = c.post("/api/kyc/submit")

    assert res.status_code == 422
    assert "government-issued ID" in res.json()["detail"]


@pytest.mark.parametrize("identity", ["passport", "national_id", "drivers_license", "identity"])
def test_any_identity_document_plus_address_is_accepted(client, identity):
    """Any one of the ID types satisfies the ID requirement."""
    c, store = client
    store[f"kyc:{USER}"] = _docs(identity, "proof_of_address")

    res = c.post("/api/kyc/submit")

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "pending"
    assert store[f"kyc:{USER}"]["status"] == "pending"
    assert store[f"kyc:{USER}"]["submitted_at"]


def test_document_types_from_the_caller_are_ignored(client):
    """A caller cannot assert documents it never uploaded.

    This is the third instance of the same shape in the audit, after
    `amount_usd` and `user_id` in checkout — and on a KYC flow it is the worst
    place for it.
    """
    c, store = client
    store[f"kyc:{USER}"] = _docs("selfie")

    res = c.post(
        "/api/kyc/submit",
        data={"document_types[]": ["passport", "proof_of_address"]},
    )

    assert res.status_code == 422, "the caller's claimed document types were trusted"
    assert store[f"kyc:{USER}"].get("status") != "pending"


def test_doc_type_matching_is_case_and_space_insensitive(client):
    c, store = client
    store[f"kyc:{USER}"] = {"documents": [{"type": " Passport "}, {"type": "PROOF_OF_ADDRESS"}]}

    assert c.post("/api/kyc/submit").status_code == 200


def test_a_failed_write_does_not_report_success(client, monkeypatch):
    """The endpoint used to catch everything and return success regardless."""
    c, store = client
    store[f"kyc:{USER}"] = _docs("passport", "proof_of_address")

    import api.db_store as db_store

    def _boom(*_a, **_kw):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(db_store, "db_set", _boom, raising=False)

    res = c.post("/api/kyc/submit")

    assert res.status_code >= 500, "a submission that was never stored reported success"
