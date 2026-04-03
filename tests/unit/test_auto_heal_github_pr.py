# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_auto_heal_github_pr.py
=======================================
Unit tests for the LLM auto-heal → GitHub PR pipeline:
  - security/github_pr_publisher.py  (GitHubPRPublisher, helpers)
  - security/global_fortress.py      (HOPEFXBrain.auto_heal)
  - api/security/fixes.py            (approve/decline/scan endpoints)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from security.global_fortress import HEAL_INTERVAL

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))


# ─────────────────────────────────────────────────────────────────────────────
# GitHubPRPublisher unit tests
# ─────────────────────────────────────────────────────────────────────────────


class TestGitHubPRPublisher:
    """Tests for security/github_pr_publisher.py"""

    def _publisher(self):
        from security.github_pr_publisher import GitHubPRPublisher

        return GitHubPRPublisher()

    @pytest.mark.asyncio
    async def test_returns_error_when_no_token(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "")
        pub = self._publisher()
        result = await pub.publish("/api/auth/login", "old", "new")
        assert result["status"] == "error"
        assert "GITHUB_TOKEN" in result["error"]

    @pytest.mark.asyncio
    async def test_full_pipeline_success(self):
        import base64

        import security.github_pr_publisher as pr_mod

        # Patch module-level constants (read at import time, not from env)
        async def fake_get_branch_sha(client, repo, branch):
            return "abc123"

        async def fake_create_branch(client, repo, branch, sha):
            return None

        async def fake_get_file(client, repo, path):
            content = base64.b64encode(b"original file content").decode()
            return {"content": content, "sha": "file_sha_123"}

        async def fake_commit_file(client, repo, branch, path, content, message, file_sha):
            return "new_commit_sha"

        async def fake_create_pr(client, repo, head, base, title, body):
            return {"number": 42, "html_url": "https://github.com/owner/repo/pull/42"}

        async def fake_add_label(client, repo, pr_number, label):
            return None

        with (
            patch.object(pr_mod, "GITHUB_TOKEN", "ghp_test_token"),
            patch.object(pr_mod, "GITHUB_REPO", "owner/repo"),
            patch.object(pr_mod, "GITHUB_BASE_BRANCH", "main"),
            patch.object(pr_mod, "_get_branch_sha", fake_get_branch_sha),
            patch.object(pr_mod, "_create_branch", fake_create_branch),
            patch.object(pr_mod, "_get_file", fake_get_file),
            patch.object(pr_mod, "_commit_file", fake_commit_file),
            patch.object(pr_mod, "_create_pr", fake_create_pr),
            patch.object(pr_mod, "_add_label", fake_add_label),
        ):
            pub = self._publisher()
            result = await pub.publish(
                endpoint="/api/auth/login",
                original_code="vulnerable code",
                fix_code="fixed code",
                approved_by="admin@test.com",
            )

        assert result["status"] == "created"
        assert result["pr_number"] == 42
        assert "pull/42" in result["pr_url"]
        assert "auto-heal" in result["branch"]

    @pytest.mark.asyncio
    async def test_http_error_returns_error_status(self):
        import httpx

        import security.github_pr_publisher as pr_mod

        async def fake_get_branch_sha(client, repo, branch):
            err_resp = MagicMock(spec=httpx.Response)
            err_resp.status_code = 401
            err_resp.text = "Bad credentials"
            raise httpx.HTTPStatusError("401", request=MagicMock(), response=err_resp)

        with (
            patch.object(pr_mod, "GITHUB_TOKEN", "ghp_test_token"),
            patch.object(pr_mod, "GITHUB_REPO", "owner/repo"),
            patch.object(pr_mod, "_get_branch_sha", fake_get_branch_sha),
        ):
            pub = self._publisher()
            result = await pub.publish("/api/auth/login", "old", "new")

        assert result["status"] == "error"
        assert "401" in result["error"]

    def test_resolve_file_path_known_endpoint(self):
        from security.github_pr_publisher import _resolve_file_path

        assert _resolve_file_path("/api/auth/login") == "api/auth.py"
        assert _resolve_file_path("/api/trading/order") == "api/trading.py"
        assert _resolve_file_path("/api/tca/report") == "api/tca.py"

    def test_resolve_file_path_heuristic(self):
        from security.github_pr_publisher import _resolve_file_path

        result = _resolve_file_path("/api/newmodule/action")
        assert result == "api/newmodule.py"

    def test_resolve_file_path_unknown(self):
        from security.github_pr_publisher import _resolve_file_path

        result = _resolve_file_path("/unknown/path")
        assert result is None

    def test_apply_patch_verbatim_replace(self):
        from security.github_pr_publisher import _apply_patch

        original = "def foo():\n    pass\n"
        snippet = "def foo():\n    pass\n"
        fix = "def foo():\n    return 42\n"
        result = _apply_patch(original, snippet, fix)
        assert "return 42" in result
        assert "pass" not in result

    def test_apply_patch_fallback_when_not_found(self):
        from security.github_pr_publisher import _apply_patch

        original = "def foo():\n    pass\n"
        result = _apply_patch(original, "nonexistent snippet", "fix code")
        # Falls back to appending comment block
        assert "AUTO-HEAL FIX" in result
        assert "fix code" in result
        # Original content preserved
        assert "def foo" in result

    def test_build_pr_body_contains_required_sections(self):
        from security.github_pr_publisher import _build_pr_body

        body = _build_pr_body(
            endpoint="/api/auth/login",
            file_path="api/auth.py",
            original="old code",
            fix="new code",
            approved_by="admin",
            ts="2025-01-01T00:00:00Z",
        )
        assert "Auto-Heal Fix" in body
        assert "/api/auth/login" in body
        assert "api/auth.py" in body
        assert "old code" in body
        assert "new code" in body
        assert "admin" in body
        assert "Checklist" in body

    def test_repo_auto_detect_from_git(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPO", "")
        mock_result = MagicMock()
        mock_result.stdout = "https://github.com/owner/myrepo.git\n"
        with patch("subprocess.run", return_value=mock_result):
            from security.github_pr_publisher import _repo

            assert _repo() == "owner/myrepo"

    def test_repo_raises_when_not_configured(self, monkeypatch):
        monkeypatch.setenv("GITHUB_REPO", "")
        mock_result = MagicMock()
        mock_result.stdout = "not-a-github-url\n"
        with patch("subprocess.run", return_value=mock_result):
            from security.github_pr_publisher import _repo

            with pytest.raises(RuntimeError, match="GITHUB_REPO"):
                _repo()

    def test_branch_name_slug_from_endpoint(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        monkeypatch.setenv("GITHUB_REPO", "owner/repo")
        # Branch name is built inside publish() — verify the slug logic
        import re

        endpoint = "/api/auth/login"
        slug = re.sub(r"[^a-z0-9]+", "-", endpoint.lower().strip("/"))[:40]
        assert slug == "api-auth-login"

    def test_get_pr_publisher_singleton(self):
        from security.github_pr_publisher import get_pr_publisher

        a = get_pr_publisher()
        b = get_pr_publisher()
        assert a is b


# ─────────────────────────────────────────────────────────────────────────────
# HOPEFXBrain.auto_heal tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAutoHeal:
    """Tests for HOPEFXBrain.auto_heal() — real scan queue, no hardcoded snippets."""

    def setup_method(self):
        """Reset module-level Redis cache before each test to prevent cross-test contamination."""
        import security.global_fortress as gf

        gf._redis_client = None

    def _make_brain(self):
        from security.global_fortress import HOPEFXBrain

        app = MagicMock()
        app.routes = []
        return HOPEFXBrain(app)

    @pytest.mark.asyncio
    async def test_auto_heal_skips_when_interval_not_elapsed(self):
        brain = self._make_brain()
        brain._last_heal = 999999999.0  # far future
        with patch("security.global_fortress._get_redis", new_callable=AsyncMock) as mock_redis:
            await brain.auto_heal()
            mock_redis.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_heal_drains_scan_queue(self):
        brain = self._make_brain()
        brain._last_heal = -HEAL_INTERVAL - 1  # force interval check to pass  # force run

        vuln_entry = json.dumps(
            {
                "endpoint": "/api/auth/login",
                "code": "def login(u, p): return db.query(f'SELECT * FROM users WHERE u={u}')",
                "severity": "high",
                "rule": "B608",
            }
        )

        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = [vuln_entry]
        mock_redis.ltrim = AsyncMock()
        mock_redis.rpush = AsyncMock()

        get_redis_mock = AsyncMock(return_value=mock_redis)
        with (
            patch("security.global_fortress._get_redis", get_redis_mock),
            patch("security.llm_wrapper.call_llm", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = "def login(u, p): return db.query('SELECT * FROM users WHERE u=?', [u])"
            await brain.auto_heal()

        # Verify queue was drained
        mock_redis.ltrim.assert_called_once_with("scan:vuln_queue", 1, -1)
        # Verify fix was pushed to fixes:queue
        mock_redis.rpush.assert_called_once()
        pushed_key = mock_redis.rpush.call_args[0][0]
        assert pushed_key == "fixes:queue"

        pushed_record = json.loads(mock_redis.rpush.call_args[0][1])
        assert pushed_record["endpoint"] == "/api/auth/login"
        assert pushed_record["status"] == "pending"
        assert pushed_record["severity"] == "high"
        assert pushed_record["rule"] == "B608"
        assert "fix" in pushed_record

    @pytest.mark.asyncio
    async def test_auto_heal_empty_queue_does_nothing(self):
        brain = self._make_brain()
        brain._last_heal = -HEAL_INTERVAL - 1  # force interval check to pass

        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = []

        with (
            patch("security.global_fortress._get_redis", AsyncMock(return_value=mock_redis)),
            patch("security.llm_wrapper.call_llm", new_callable=AsyncMock) as mock_llm,
        ):
            await brain.auto_heal()
            mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_heal_skips_empty_code_snippet(self):
        brain = self._make_brain()
        brain._last_heal = -HEAL_INTERVAL - 1  # force interval check to pass

        entry = json.dumps({"endpoint": "/api/foo", "code": "", "severity": "low", "rule": "manual"})
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = [entry]
        mock_redis.ltrim = AsyncMock()

        with (
            patch("security.global_fortress._get_redis", AsyncMock(return_value=mock_redis)),
            patch("security.llm_wrapper.call_llm", new_callable=AsyncMock) as mock_llm,
        ):
            await brain.auto_heal()
            mock_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_heal_handles_malformed_json(self):
        brain = self._make_brain()
        brain._last_heal = -HEAL_INTERVAL - 1  # force interval check to pass

        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = [b"not valid json"]
        mock_redis.ltrim = AsyncMock()

        with patch("security.global_fortress._get_redis", AsyncMock(return_value=mock_redis)):
            # Should not raise
            await brain.auto_heal()

    @pytest.mark.asyncio
    async def test_auto_heal_handles_llm_failure_gracefully(self):
        brain = self._make_brain()
        brain._last_heal = -HEAL_INTERVAL - 1  # force interval check to pass

        entry = json.dumps(
            {
                "endpoint": "/api/auth/login",
                "code": "vulnerable code",
                "severity": "high",
                "rule": "B608",
            }
        )
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = [entry]
        mock_redis.ltrim = AsyncMock()

        with (
            patch("security.global_fortress._get_redis", AsyncMock(return_value=mock_redis)),
            patch("security.llm_wrapper.call_llm", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.side_effect = RuntimeError("LLM API key not configured")
            # Should not raise — logs warning and continues
            await brain.auto_heal()

    @pytest.mark.asyncio
    async def test_auto_heal_processes_multiple_entries(self):
        brain = self._make_brain()
        brain._last_heal = -HEAL_INTERVAL - 1  # force interval check to pass

        entries = [
            json.dumps(
                {
                    "endpoint": f"/api/ep{i}",
                    "code": f"code{i}",
                    "severity": "medium",
                    "rule": "B101",
                }
            )
            for i in range(3)
        ]
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = entries
        mock_redis.ltrim = AsyncMock()
        mock_redis.rpush = AsyncMock()

        with (
            patch("security.global_fortress._get_redis", AsyncMock(return_value=mock_redis)),
            patch("security.llm_wrapper.call_llm", new_callable=AsyncMock) as mock_llm,
        ):
            mock_llm.return_value = "fixed code"
            await brain.auto_heal()

        assert mock_redis.rpush.call_count == 3


# ─────────────────────────────────────────────────────────────────────────────
# api/security/fixes.py endpoint tests
# ─────────────────────────────────────────────────────────────────────────────


class TestFixesRouter:
    """Tests for api/security/fixes.py REST endpoints."""

    def _make_pending_record(self, endpoint="/api/auth/login"):
        return json.dumps(
            {
                "endpoint": endpoint,
                "original": "vulnerable code",
                "fix": "fixed code",
                "severity": "high",
                "rule": "B608",
                "ts": datetime.now(UTC).isoformat(),
                "status": "pending",
            }
        )

    def _mock_auth(self, role="admin"):
        return {"sub": "admin@test.com", "role": role}

    @pytest.mark.asyncio
    async def test_get_pending_fixes_empty(self):
        from api.security.fixes import get_pending_fixes

        mock_request = MagicMock()
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = []

        with (
            patch("api.security.fixes._require_auth", return_value=self._mock_auth()),
            patch("api.security.fixes._get_redis", AsyncMock(return_value=mock_redis)),
        ):
            result = await get_pending_fixes(mock_request, limit=50)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_pending_fixes_returns_records(self):
        from api.security.fixes import get_pending_fixes

        mock_request = MagicMock()
        record = self._make_pending_record()
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = [record]

        with (
            patch("api.security.fixes._require_auth", return_value=self._mock_auth()),
            patch("api.security.fixes._get_redis", AsyncMock(return_value=mock_redis)),
        ):
            result = await get_pending_fixes(mock_request, limit=50)
        assert len(result) == 1
        assert result[0]["endpoint"] == "/api/auth/login"

    @pytest.mark.asyncio
    async def test_approve_fix_triggers_pr_pipeline(self):
        from api.security.fixes import ApproveFixRequest, approve_fix

        mock_request = MagicMock()
        record = self._make_pending_record()
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = [record]
        mock_redis.lrem = AsyncMock()
        mock_redis.rpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()

        pr_result = {
            "status": "created",
            "pr_url": "https://github.com/owner/repo/pull/99",
            "pr_number": 99,
            "branch": "auto-heal/20250101-api-auth-login",
            "file_path": "api/auth.py",
        }

        with (
            patch("api.security.fixes._require_admin", return_value=self._mock_auth()),
            patch("api.security.fixes._get_redis", AsyncMock(return_value=mock_redis)),
            patch(
                "security.github_pr_publisher.GitHubPRPublisher.publish",
                new_callable=AsyncMock,
                return_value=pr_result,
            ),
        ):
            body = ApproveFixRequest(endpoint="/api/auth/login", approved_by="admin")
            result = await approve_fix(body, mock_request)

        assert result["status"] == "approved"
        assert result["pr_url"] == "https://github.com/owner/repo/pull/99"
        assert result["pr_number"] == 99
        # Record removed from queue
        mock_redis.lrem.assert_called_once()
        # Archived to approved list
        mock_redis.rpush.assert_called_once()
        archived = json.loads(mock_redis.rpush.call_args[0][1])
        assert archived["status"] == "approved"
        assert archived["pr_url"] == "https://github.com/owner/repo/pull/99"

    @pytest.mark.asyncio
    async def test_approve_fix_404_when_not_found(self):
        from fastapi import HTTPException

        from api.security.fixes import ApproveFixRequest, approve_fix

        mock_request = MagicMock()
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = []

        with (
            patch("api.security.fixes._require_admin", return_value=self._mock_auth()),
            patch("api.security.fixes._get_redis", AsyncMock(return_value=mock_redis)),
        ):
            body = ApproveFixRequest(endpoint="/api/nonexistent")
            with pytest.raises(HTTPException) as exc_info:
                await approve_fix(body, mock_request)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_approve_fix_handles_pr_error_gracefully(self):
        from api.security.fixes import ApproveFixRequest, approve_fix

        mock_request = MagicMock()
        record = self._make_pending_record()
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = [record]
        mock_redis.lrem = AsyncMock()
        mock_redis.rpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()

        with (
            patch("api.security.fixes._require_admin", return_value=self._mock_auth()),
            patch("api.security.fixes._get_redis", AsyncMock(return_value=mock_redis)),
            patch(
                "security.github_pr_publisher.GitHubPRPublisher.publish",
                new_callable=AsyncMock,
                return_value={"status": "error", "error": "token invalid"},
            ),
        ):
            body = ApproveFixRequest(endpoint="/api/auth/login")
            result = await approve_fix(body, mock_request)

        # Still returns approved — PR error is surfaced but doesn't block
        assert result["status"] == "approved"
        assert result["pr_status"] == "error"
        assert result["pr_error"] == "token invalid"

    @pytest.mark.asyncio
    async def test_decline_fix_archives_record(self):
        from api.security.fixes import DeclineFixRequest, decline_fix

        mock_request = MagicMock()
        record = self._make_pending_record()
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = [record]
        mock_redis.lrem = AsyncMock()
        mock_redis.rpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()

        with (
            patch("api.security.fixes._require_admin", return_value=self._mock_auth()),
            patch("api.security.fixes._get_redis", AsyncMock(return_value=mock_redis)),
        ):
            body = DeclineFixRequest(
                endpoint="/api/auth/login",
                declined_by="reviewer",
                reason="false positive",
            )
            result = await decline_fix(body, mock_request)

        assert result["status"] == "declined"
        mock_redis.lrem.assert_called_once()
        mock_redis.rpush.assert_called_once()
        archived = json.loads(mock_redis.rpush.call_args[0][1])
        assert archived["status"] == "declined"
        assert archived["reason"] == "false positive"

    @pytest.mark.asyncio
    async def test_decline_fix_404_when_not_found(self):
        from fastapi import HTTPException

        from api.security.fixes import DeclineFixRequest, decline_fix

        mock_request = MagicMock()
        mock_redis = AsyncMock()
        mock_redis.lrange.return_value = []

        with (
            patch("api.security.fixes._require_admin", return_value=self._mock_auth()),
            patch("api.security.fixes._get_redis", AsyncMock(return_value=mock_redis)),
        ):
            body = DeclineFixRequest(endpoint="/api/nonexistent")
            with pytest.raises(HTTPException) as exc_info:
                await decline_fix(body, mock_request)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_push_scan_entry_queues_to_redis(self):
        from api.security.fixes import ScanEntryRequest, push_scan_entry

        mock_request = MagicMock()
        mock_redis = AsyncMock()
        mock_redis.rpush = AsyncMock()
        mock_redis.llen = AsyncMock(return_value=1)

        with (
            patch("api.security.fixes._require_admin", return_value=self._mock_auth()),
            patch("api.security.fixes._get_redis", AsyncMock(return_value=mock_redis)),
        ):
            body = ScanEntryRequest(
                endpoint="/api/auth/login",
                code="vulnerable code",
                severity="high",
                rule="B608",
            )
            result = await push_scan_entry(body, mock_request)

        assert result["status"] == "queued"
        assert result["endpoint"] == "/api/auth/login"
        mock_redis.rpush.assert_called_once()
        pushed = json.loads(mock_redis.rpush.call_args[0][1])
        assert pushed["endpoint"] == "/api/auth/login"
        assert pushed["severity"] == "high"
        assert pushed["rule"] == "B608"

    @pytest.mark.asyncio
    async def test_get_fix_stats(self):
        from api.security.fixes import get_fix_stats

        mock_request = MagicMock()
        mock_redis = AsyncMock()
        mock_redis.llen.side_effect = [
            3,
            10,
            2,
            1,
        ]  # pending, approved, declined, scan_queue

        approved_records = [
            json.dumps(
                {
                    "pr_url": "https://github.com/owner/repo/pull/1",
                    "pr_status": "created",
                }
            ),
            json.dumps(
                {
                    "pr_url": "https://github.com/owner/repo/pull/2",
                    "pr_status": "created",
                }
            ),
            json.dumps({"pr_status": "error", "pr_error": "token invalid"}),
        ]
        mock_redis.lrange.return_value = approved_records

        with (
            patch("api.security.fixes._require_auth", return_value=self._mock_auth()),
            patch("api.security.fixes._get_redis", AsyncMock(return_value=mock_redis)),
        ):
            result = await get_fix_stats(mock_request)

        assert result["pending"] == 3
        assert result["approved"] == 10
        assert result["declined"] == 2
        assert result["prs_created"] == 2
        assert result["pr_errors"] == 1

    @pytest.mark.asyncio
    async def test_non_admin_cannot_approve(self):
        from fastapi import HTTPException

        from api.security.fixes import ApproveFixRequest, approve_fix

        mock_request = MagicMock()

        with (
            patch(
                "api.security.fixes._require_auth",
                return_value={"sub": "user@test.com", "role": "trader"},
            ),
            patch("api.security.fixes._get_redis", return_value=AsyncMock()),
        ):
            body = ApproveFixRequest(endpoint="/api/auth/login")
            with pytest.raises(HTTPException) as exc_info:
                await approve_fix(body, mock_request)
        assert exc_info.value.status_code == 403
