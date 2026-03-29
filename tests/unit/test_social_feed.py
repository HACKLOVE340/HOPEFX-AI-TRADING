# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_social_feed.py
==============================
Unit tests for api/social_feed.py:
- _publish_signal()     — signal publication helper
- GET /api/feed         — paginated feed
- POST /api/feed/{id}/react    — reaction toggle
- POST /api/feed/{id}/comment  — comment creation
- GET  /api/feed/{id}/comments — comment listing
- POST /api/feed/opt-in / opt-out — user preference
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_social_feed_state():
    """Reset in-memory stores before each test."""
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
def mock_user():
    """Mock authenticated user token payload."""
    user = MagicMock()
    user.sub = "user_test_001"
    user.username = "testtrader"
    return user


@pytest.fixture
def app(mock_user):
    """FastAPI test app with social feed router and auth dependency overridden."""
    from api.social_feed import router, leaderboard_router
    from api.auth import get_current_user

    _app = FastAPI()
    _app.include_router(router)
    _app.include_router(leaderboard_router)
    # Override auth so all tests can call authenticated endpoints without a JWT
    _app.dependency_overrides[get_current_user] = lambda: mock_user
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


def _make_signal(signal_id: str = None, confidence: float = 75.0) -> dict:
    return {
        "signal_id": signal_id or str(uuid.uuid4()),
        "symbol": "XAU/USD",
        "direction": "BUY",
        "confidence": confidence,
        "entry_price": 1923.5,
        "pnl": 0.0,
    }


# ── _publish_signal() tests ───────────────────────────────────────────────────


class TestPublishSignal:
    def test_publish_signal_creates_feed_item(self):
        """_publish_signal() adds item to _feed_items."""
        import api.social_feed as sf

        signal = _make_signal("sig_001")
        item = sf._publish_signal(signal, username="alice", trader_id="trader_1")

        assert "sig_001" in sf._feed_items
        assert item["signal_id"] == "sig_001"
        assert item["username"] == "alice"
        assert item["is_public"] is True

    def test_publish_signal_initialises_reactions_and_comments(self):
        """_publish_signal() initialises empty reactions and comments."""
        import api.social_feed as sf

        signal = _make_signal("sig_002")
        sf._publish_signal(signal, username="bob", trader_id="trader_2")

        assert sf._reactions["sig_002"] == {}
        assert sf._comments["sig_002"] == []

    def test_publish_signal_generates_uuid_when_no_signal_id(self):
        """_publish_signal() generates a UUID when signal has no signal_id."""
        import api.social_feed as sf

        signal = {"symbol": "EUR/USD", "direction": "SELL", "confidence": 80.0}
        item = sf._publish_signal(signal, username="carol", trader_id="trader_3")

        assert item["signal_id"] is not None
        assert len(item["signal_id"]) > 0

    def test_publish_signal_sets_correct_defaults(self):
        """_publish_signal() sets thumbs_up=0, thumbs_down=0, copies=0."""
        import api.social_feed as sf

        signal = _make_signal("sig_defaults")
        item = sf._publish_signal(signal, username="dave", trader_id="trader_4")

        assert item["thumbs_up"] == 0
        assert item["thumbs_down"] == 0
        assert item["copies"] == 0
        assert item["comment_count"] == 0


# ── GET /api/feed tests ───────────────────────────────────────────────────────


class TestGetFeed:
    def test_empty_feed_returns_empty_list(self, client):
        """GET /api/feed returns empty list when no signals published."""
        response = client.get("/api/feed")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_feed_returns_published_signals(self, client):
        """GET /api/feed returns all published signals."""
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_a"), "alice", "t1")
        sf._publish_signal(_make_signal("sig_b"), "bob", "t2")

        response = client.get("/api/feed")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2

    def test_feed_filters_by_symbol(self, client):
        """GET /api/feed?symbol=XAU/USD filters correctly."""
        import api.social_feed as sf

        sf._publish_signal(
            {"signal_id": "sig_gold", "symbol": "XAU/USD", "direction": "BUY", "confidence": 75.0},
            "alice", "t1",
        )
        sf._publish_signal(
            {"signal_id": "sig_eur", "symbol": "EUR/USD", "direction": "SELL", "confidence": 72.0},
            "bob", "t2",
        )

        response = client.get("/api/feed?symbol=XAU/USD")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["signal_id"] == "sig_gold"

    def test_feed_pagination(self, client):
        """GET /api/feed respects page and limit parameters."""
        import api.social_feed as sf

        for i in range(5):
            sf._publish_signal(_make_signal(f"sig_{i}"), f"user_{i}", f"t{i}")

        response = client.get("/api/feed?page=1&limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 3
        assert data["total"] == 5
        assert data["pages"] == 2

    def test_feed_sorted_newest_first(self, client):
        """GET /api/feed returns items sorted newest first."""
        import api.social_feed as sf
        import time

        sf._publish_signal(_make_signal("sig_old"), "alice", "t1")
        time.sleep(0.01)
        sf._publish_signal(_make_signal("sig_new"), "bob", "t2")

        response = client.get("/api/feed")
        data = response.json()
        ids = [item["signal_id"] for item in data["items"]]
        assert ids[0] == "sig_new"
        assert ids[1] == "sig_old"

    def test_feed_excludes_private_items(self, client):
        """GET /api/feed excludes items where is_public=False."""
        import api.social_feed as sf

        item = sf._publish_signal(_make_signal("sig_private"), "alice", "t1")
        item["is_public"] = False

        response = client.get("/api/feed")
        data = response.json()
        assert data["total"] == 0


# ── POST /api/feed/{id}/react tests ──────────────────────────────────────────


class TestReactToSignal:
    def test_thumbs_up_increments_count(self, client, mock_user):
        """POST /react with 'up' increments thumbs_up."""
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_react"), "alice", "t1")

        with patch("api.social_feed.get_current_user", return_value=mock_user):
            response = client.post(
                "/api/feed/sig_react/react",
                json={"reaction": "up"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["thumbs_up"] == 1
        assert data["thumbs_down"] == 0
        assert data["your_reaction"] == "up"

    def test_thumbs_down_increments_count(self, client, mock_user):
        """POST /react with 'down' increments thumbs_down."""
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_down"), "alice", "t1")

        with patch("api.social_feed.get_current_user", return_value=mock_user):
            response = client.post(
                "/api/feed/sig_down/react",
                json={"reaction": "down"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["thumbs_down"] == 1
        assert data["your_reaction"] == "down"

    def test_same_reaction_twice_toggles_off(self, client, mock_user):
        """Clicking the same reaction twice removes it (toggle)."""
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_toggle"), "alice", "t1")

        with patch("api.social_feed.get_current_user", return_value=mock_user):
            client.post("/api/feed/sig_toggle/react", json={"reaction": "up"})
            response = client.post("/api/feed/sig_toggle/react", json={"reaction": "up"})

        data = response.json()
        assert data["thumbs_up"] == 0
        assert data["your_reaction"] is None

    def test_changing_reaction_updates_counts(self, client, mock_user):
        """Changing from 'up' to 'down' adjusts both counts correctly."""
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_change"), "alice", "t1")

        with patch("api.social_feed.get_current_user", return_value=mock_user):
            client.post("/api/feed/sig_change/react", json={"reaction": "up"})
            response = client.post("/api/feed/sig_change/react", json={"reaction": "down"})

        data = response.json()
        assert data["thumbs_up"] == 0
        assert data["thumbs_down"] == 1
        assert data["your_reaction"] == "down"

    def test_react_to_nonexistent_signal_returns_404(self, client, mock_user):
        """POST /react on unknown signal_id returns 404."""
        with patch("api.social_feed.get_current_user", return_value=mock_user):
            response = client.post(
                "/api/feed/nonexistent_signal/react",
                json={"reaction": "up"},
            )
        assert response.status_code == 404

    def test_invalid_reaction_value_returns_422(self, client, mock_user):
        """POST /react with invalid reaction value returns 422."""
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_invalid"), "alice", "t1")

        with patch("api.social_feed.get_current_user", return_value=mock_user):
            response = client.post(
                "/api/feed/sig_invalid/react",
                json={"reaction": "sideways"},
            )
        assert response.status_code == 422


# ── POST /api/feed/{id}/comment tests ────────────────────────────────────────


class TestAddComment:
    def test_add_comment_creates_comment(self, client, mock_user):
        """POST /comment creates a comment and returns it."""
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_comment"), "alice", "t1")

        with patch("api.social_feed.get_current_user", return_value=mock_user):
            response = client.post(
                "/api/feed/sig_comment/comment",
                json={"text": "Great signal!"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["text"] == "Great signal!"
        assert data["signal_id"] == "sig_comment"
        assert "comment_id" in data
        assert "created_at" in data

    def test_add_comment_increments_comment_count(self, client, mock_user):
        """POST /comment increments the signal's comment_count."""
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_count"), "alice", "t1")

        with patch("api.social_feed.get_current_user", return_value=mock_user):
            client.post("/api/feed/sig_count/comment", json={"text": "First!"})
            client.post("/api/feed/sig_count/comment", json={"text": "Second!"})

        assert sf._feed_items["sig_count"]["comment_count"] == 2

    def test_add_comment_to_nonexistent_signal_returns_404(self, client, mock_user):
        """POST /comment on unknown signal_id returns 404."""
        with patch("api.social_feed.get_current_user", return_value=mock_user):
            response = client.post(
                "/api/feed/no_such_signal/comment",
                json={"text": "Hello?"},
            )
        assert response.status_code == 404

    def test_empty_comment_returns_422(self, client, mock_user):
        """POST /comment with empty text returns 422."""
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_empty"), "alice", "t1")

        with patch("api.social_feed.get_current_user", return_value=mock_user):
            response = client.post(
                "/api/feed/sig_empty/comment",
                json={"text": ""},
            )
        assert response.status_code == 422

    def test_comment_too_long_returns_422(self, client, mock_user):
        """POST /comment with text > 500 chars returns 422."""
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_long"), "alice", "t1")

        with patch("api.social_feed.get_current_user", return_value=mock_user):
            response = client.post(
                "/api/feed/sig_long/comment",
                json={"text": "x" * 501},
            )
        assert response.status_code == 422


# ── GET /api/feed/{id}/comments tests ────────────────────────────────────────


class TestGetComments:
    def test_get_comments_returns_empty_list_initially(self, client):
        """GET /comments returns empty list for new signal."""
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_nocomments"), "alice", "t1")

        response = client.get("/api/feed/sig_nocomments/comments")
        assert response.status_code == 200
        data = response.json()
        assert data["comments"] == []

    def test_get_comments_returns_all_comments(self, client, mock_user):
        """GET /comments returns all comments in order."""
        import api.social_feed as sf

        sf._publish_signal(_make_signal("sig_multi"), "alice", "t1")

        with patch("api.social_feed.get_current_user", return_value=mock_user):
            client.post("/api/feed/sig_multi/comment", json={"text": "First"})
            client.post("/api/feed/sig_multi/comment", json={"text": "Second"})

        response = client.get("/api/feed/sig_multi/comments")
        data = response.json()
        assert len(data["comments"]) == 2
        assert data["comments"][0]["text"] == "First"
        assert data["comments"][1]["text"] == "Second"

    def test_get_comments_for_nonexistent_signal_returns_404(self, client):
        """GET /comments on unknown signal_id returns 404."""
        response = client.get("/api/feed/ghost_signal/comments")
        assert response.status_code == 404


# ── Opt-in / opt-out tests ────────────────────────────────────────────────────


class TestOptInOut:
    def test_opt_in_adds_user_to_opted_in_set(self, client, mock_user):
        """POST /opt-in adds user to _opted_in."""
        import api.social_feed as sf

        with patch("api.social_feed.get_current_user", return_value=mock_user), \
             patch("api.social_feed._save_opted_in"):
            response = client.post("/api/feed/opt-in")

        assert response.status_code == 200
        assert mock_user.sub in sf._opted_in

    def test_opt_out_removes_user_from_opted_in_set(self, client, mock_user):
        """POST /opt-out removes user from _opted_in."""
        import api.social_feed as sf

        sf._opted_in.add(mock_user.sub)

        with patch("api.social_feed.get_current_user", return_value=mock_user), \
             patch("api.social_feed._save_opted_in"):
            response = client.post("/api/feed/opt-out")

        assert response.status_code == 200
        assert mock_user.sub not in sf._opted_in

    def test_opt_in_is_idempotent(self, client, mock_user):
        """POST /opt-in twice does not raise an error."""
        import api.social_feed as sf

        with patch("api.social_feed.get_current_user", return_value=mock_user), \
             patch("api.social_feed._save_opted_in"):
            client.post("/api/feed/opt-in")
            response = client.post("/api/feed/opt-in")

        assert response.status_code == 200
        assert mock_user.sub in sf._opted_in
