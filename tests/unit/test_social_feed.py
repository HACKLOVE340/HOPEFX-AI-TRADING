# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_social_feed.py
==============================
Unit tests for api/social_feed.py.

Auth is handled entirely via FastAPI dependency_overrides — no patching of
module-level attributes, which breaks when the module is already imported.
"""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import TokenPayload


@pytest.fixture(autouse=True)
def reset_social_feed_state():
    import api.social_feed as sf

    sf._feed_items.clear()
    sf._reactions.clear()
    sf._comments.clear()
    sf._opted_in.clear()
    yield
    sf._feed_items.clear()
    sf._reactions.clear()
    sf._comments.clear()
    sf._opted_in.clear()


@pytest.fixture
def stub_user() -> TokenPayload:
    return TokenPayload(sub="user_test_001", role="trader", exp=9_999_999_999)


@pytest.fixture
def app(stub_user: TokenPayload) -> FastAPI:
    import importlib
    import sys

    # Always use the canonical module instances — survive any sys.modules reloads
    # performed by other tests (e.g. test_oanda_paper_clock clears sys.modules).
    auth_mod = sys.modules.get("api.auth") or importlib.import_module("api.auth")
    sf_mod = sys.modules.get("api.social_feed") or importlib.import_module("api.social_feed")

    _app = FastAPI()
    _app.include_router(sf_mod.router)
    _app.include_router(sf_mod.leaderboard_router)
    # Override using the exact function object the router captured at import time
    _app.dependency_overrides[sf_mod.get_current_user] = lambda: stub_user
    # Also override via auth module reference in case FastAPI resolves it there
    _app.dependency_overrides[auth_mod.get_current_user] = lambda: stub_user
    return _app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _make_signal(signal_id=None, confidence=75.0):
    return {
        "signal_id": signal_id or str(uuid.uuid4()),
        "symbol": "XAU/USD",
        "direction": "BUY",
        "confidence": confidence,
        "entry_price": 1923.5,
        "pnl": 0.0,
    }


class TestPublishSignal:
    def test_publish_signal_creates_feed_item(self):
        import api.social_feed as sf

        item = sf._publish_signal(_make_signal("sig_001"), username="alice", trader_id="t1")
        assert "sig_001" in sf._feed_items
        assert item["signal_id"] == "sig_001"
        assert item["username"] == "alice"
        assert item["is_public"] is True

    def test_publish_signal_initialises_reactions_and_comments(self):
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_002"), username="bob", trader_id="t2")
        assert sf._reactions["sig_002"] == {}
        assert sf._comments["sig_002"] == []

    def test_publish_signal_generates_uuid_when_no_signal_id(self):
        import api.social_feed as sf

        item = sf._publish_signal(
            {"symbol": "EUR/USD", "direction": "SELL", "confidence": 80.0},
            username="carol",
            trader_id="t3",
        )
        assert item["signal_id"] is not None
        assert len(item["signal_id"]) > 0

    def test_publish_signal_sets_correct_defaults(self):
        import api.social_feed as sf

        item = sf._publish_signal(_make_signal("sig_defaults"), username="dave", trader_id="t4")
        assert item["thumbs_up"] == 0
        assert item["thumbs_down"] == 0
        assert item["copies"] == 0
        assert item["comment_count"] == 0


class TestGetFeed:
    def test_empty_feed_returns_empty_list(self, client):
        r = client.get("/api/feed")
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_feed_returns_published_signals(self, client):
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_a"), "alice", "t1")
        sf._publish_signal(_make_signal("sig_b"), "bob", "t2")
        r = client.get("/api/feed")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2

    def test_feed_filters_by_symbol(self, client):
        import api.social_feed as sf

        sf._publish_signal(
            {
                "signal_id": "sig_gold",
                "symbol": "XAU/USD",
                "direction": "BUY",
                "confidence": 75.0,
            },
            "alice",
            "t1",
        )
        sf._publish_signal(
            {
                "signal_id": "sig_eur",
                "symbol": "EUR/USD",
                "direction": "SELL",
                "confidence": 72.0,
            },
            "bob",
            "t2",
        )
        r = client.get("/api/feed?symbol=XAU/USD")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["signal_id"] == "sig_gold"

    def test_feed_pagination(self, client):
        import api.social_feed as sf

        for i in range(5):
            sf._publish_signal(_make_signal(f"sig_{i}"), f"user_{i}", f"t{i}")
        r = client.get("/api/feed?page=1&limit=3")
        assert r.status_code == 200
        data = r.json()
        assert len(data["items"]) == 3
        assert data["total"] == 5
        assert data["pages"] == 2

    def test_feed_sorted_newest_first(self, client):
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_old"), "alice", "t1")
        time.sleep(0.01)
        sf._publish_signal(_make_signal("sig_new"), "bob", "t2")
        r = client.get("/api/feed")
        ids = [item["signal_id"] for item in r.json()["items"]]
        assert ids[0] == "sig_new"

    def test_feed_excludes_private_items(self, client):
        import api.social_feed as sf

        item = sf._publish_signal(_make_signal("sig_private"), "alice", "t1")
        item["is_public"] = False
        r = client.get("/api/feed")
        assert r.json()["total"] == 0


class TestReactToSignal:
    def test_thumbs_up_increments_count(self, client):
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_react"), "alice", "t1")
        r = client.post("/api/feed/sig_react/react", json={"reaction": "up"})
        assert r.status_code == 200
        data = r.json()
        assert data["thumbs_up"] == 1
        assert data["thumbs_down"] == 0
        assert data["your_reaction"] == "up"

    def test_thumbs_down_increments_count(self, client):
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_down"), "alice", "t1")
        r = client.post("/api/feed/sig_down/react", json={"reaction": "down"})
        assert r.status_code == 200
        assert r.json()["thumbs_down"] == 1

    def test_same_reaction_twice_toggles_off(self, client):
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_toggle"), "alice", "t1")
        client.post("/api/feed/sig_toggle/react", json={"reaction": "up"})
        r = client.post("/api/feed/sig_toggle/react", json={"reaction": "up"})
        data = r.json()
        assert data["thumbs_up"] == 0
        assert data["your_reaction"] is None

    def test_changing_reaction_updates_counts(self, client):
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_change"), "alice", "t1")
        client.post("/api/feed/sig_change/react", json={"reaction": "up"})
        r = client.post("/api/feed/sig_change/react", json={"reaction": "down"})
        data = r.json()
        assert data["thumbs_up"] == 0
        assert data["thumbs_down"] == 1

    def test_react_to_nonexistent_signal_returns_404(self, client):
        r = client.post("/api/feed/nonexistent_signal/react", json={"reaction": "up"})
        assert r.status_code == 404

    def test_invalid_reaction_value_returns_422(self, client):
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_invalid"), "alice", "t1")
        r = client.post("/api/feed/sig_invalid/react", json={"reaction": "sideways"})
        assert r.status_code == 422


class TestAddComment:
    def test_add_comment_creates_comment(self, client):
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_comment"), "alice", "t1")
        r = client.post("/api/feed/sig_comment/comment", json={"text": "Great signal!"})
        assert r.status_code == 200
        data = r.json()
        assert data["text"] == "Great signal!"
        assert data["signal_id"] == "sig_comment"
        assert "comment_id" in data

    def test_add_comment_increments_comment_count(self, client):
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_count"), "alice", "t1")
        client.post("/api/feed/sig_count/comment", json={"text": "First!"})
        client.post("/api/feed/sig_count/comment", json={"text": "Second!"})
        assert sf._feed_items["sig_count"]["comment_count"] == 2

    def test_add_comment_to_nonexistent_signal_returns_404(self, client):
        r = client.post("/api/feed/no_such_signal/comment", json={"text": "Hello?"})
        assert r.status_code == 404

    def test_empty_comment_returns_422(self, client):
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_empty"), "alice", "t1")
        r = client.post("/api/feed/sig_empty/comment", json={"text": ""})
        assert r.status_code == 422

    def test_comment_too_long_returns_422(self, client):
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_long"), "alice", "t1")
        r = client.post("/api/feed/sig_long/comment", json={"text": "x" * 501})
        assert r.status_code == 422


class TestGetComments:
    def test_get_comments_returns_empty_list_initially(self, client):
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_nocomments"), "alice", "t1")
        r = client.get("/api/feed/sig_nocomments/comments")
        assert r.status_code == 200
        assert r.json()["comments"] == []

    def test_get_comments_returns_all_comments(self, client):
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_multi"), "alice", "t1")
        client.post("/api/feed/sig_multi/comment", json={"text": "First"})
        client.post("/api/feed/sig_multi/comment", json={"text": "Second"})
        r = client.get("/api/feed/sig_multi/comments")
        data = r.json()
        assert len(data["comments"]) == 2
        assert data["comments"][0]["text"] == "First"

    def test_get_comments_for_nonexistent_signal_returns_404(self, client):
        r = client.get("/api/feed/ghost_signal/comments")
        assert r.status_code == 404


class TestOptInOut:
    def test_opt_in_adds_user_to_opted_in_set(self, client, stub_user):
        import api.social_feed as sf

        r = client.post("/api/feed/opt-in")
        assert r.status_code == 200
        assert stub_user.sub in sf._opted_in

    def test_opt_out_removes_user_from_opted_in_set(self, client, stub_user):
        import api.social_feed as sf

        sf._opted_in.add(stub_user.sub)
        r = client.post("/api/feed/opt-out")
        assert r.status_code == 200
        assert stub_user.sub not in sf._opted_in

    def test_opt_in_is_idempotent(self, client, stub_user):
        import api.social_feed as sf

        client.post("/api/feed/opt-in")
        r = client.post("/api/feed/opt-in")
        assert r.status_code == 200
        assert stub_user.sub in sf._opted_in
