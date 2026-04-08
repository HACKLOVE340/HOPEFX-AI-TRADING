# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
security/github_pr_publisher.py
================================
LLM auto-heal → GitHub Pull Request pipeline.

When an operator approves an LLM-generated fix in the dashboard, this
module:

  1. Resolves the target file path from the endpoint name.
  2. Fetches the current file content from GitHub via the REST API.
  3. Applies the LLM patch (replaces the vulnerable code block).
  4. Creates a new branch: auto-heal/{timestamp}-{slug}.
  5. Commits the patched file to that branch.
  6. Opens a GitHub Pull Request with a structured description.
  7. Returns the PR URL for display in the dashboard.

Configuration (env vars)
------------------------
GITHUB_TOKEN          — Personal access token or GitHub App token with
                        repo + pull_request write scopes. Required.
GITHUB_REPO           — Owner/repo slug, e.g. "HACKLOVE340/HOPEFX-AI-TRADING".
                        Defaults to the current repo detected from git remote.
GITHUB_BASE_BRANCH    — Target branch for PRs (default: "main").
GITHUB_PR_LABEL       — Label applied to auto-heal PRs (default: "auto-heal").
GITHUB_PR_DRAFT       — Open PRs as drafts (default: "false").

Security
--------
- The LLM fix is NEVER applied directly to the working tree or committed
  without an explicit operator approval action.
- The PR is opened against the configured base branch; it requires a
  human code review before merge.
- The GitHub token is read from the environment only — never logged.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import textwrap
from datetime import datetime, timezone

UTC = timezone.utc
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO: str = os.getenv("GITHUB_REPO", "")
GITHUB_BASE_BRANCH: str = os.getenv("GITHUB_BASE_BRANCH", "main")
GITHUB_PR_LABEL: str = os.getenv("GITHUB_PR_LABEL", "auto-heal")
GITHUB_PR_DRAFT: bool = os.getenv("GITHUB_PR_DRAFT", "false").lower() == "true"

_GITHUB_API = "https://api.github.com"
_TIMEOUT = 30.0


# ── Endpoint → file path resolver ─────────────────────────────────────────────

# Maps known API endpoint prefixes to source file paths.
# Extend this dict as new modules are added.
_ENDPOINT_FILE_MAP: dict[str, str] = {
    "/api/auth/login": "api/auth.py",
    "/api/auth/register": "api/auth.py",
    "/api/auth/refresh": "api/auth.py",
    "/api/trading/order": "api/trading.py",
    "/api/trading/positions": "api/trading.py",
    "/api/trading/signals": "api/signals.py",
    "/api/risk/": "api/risk.py",
    "/api/tca/": "api/tca.py",
    "/api/security/": "security/global_fortress.py",
    "/api/broker/": "api/broker.py",
    "/api/user/": "api/users.py",
    "/api/admin/": "api/admin.py",
    "/api/payments/": "api/payments.py",
    "/api/compliance/": "api/compliance.py",
}


def _resolve_file_path(endpoint: str) -> str | None:
    """
    Map an API endpoint string to a source file path.

    Returns None if no mapping is found — the PR will include the raw
    endpoint name and the operator must apply the fix manually.
    """
    for prefix, path in _ENDPOINT_FILE_MAP.items():
        if endpoint.startswith(prefix):
            return path
    # Heuristic: /api/foo/bar → api/foo.py
    parts = endpoint.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "api":
        return f"api/{parts[1]}.py"
    return None


# ── GitHub API helpers ────────────────────────────────────────────────────────


def _headers() -> dict[str, str]:
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is not set. Configure it to enable the auto-heal PR pipeline.")
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _repo() -> str:
    """Return owner/repo, auto-detecting from git remote if not set."""
    if GITHUB_REPO:
        return GITHUB_REPO
    # Auto-detect from git remote
    try:
        import subprocess  # nosec B404 - list-form git call; no shell=True, no user input

        result = subprocess.run(  # nosec B603 B607 - list-form git call; no shell=True, no user input
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        url = result.stdout.strip()
        # https://github.com/owner/repo.git  or  git@github.com:owner/repo.git
        match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
        if match:
            return match.group(1)
    except Exception as exc:
        logger.debug("Auto-detect repo failed: %s", exc)
    raise RuntimeError("GITHUB_REPO is not set and could not be auto-detected from git remote.")


async def _get_file(client: httpx.AsyncClient, repo: str, path: str) -> dict[str, Any] | None:
    """Fetch file metadata and content from GitHub. Returns None if not found."""
    url = f"{_GITHUB_API}/repos/{repo}/contents/{path}"
    resp = await client.get(url, headers=_headers(), params={"ref": GITHUB_BASE_BRANCH})
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


async def _get_branch_sha(client: httpx.AsyncClient, repo: str, branch: str) -> str:
    """Return the HEAD commit SHA of *branch*."""
    url = f"{_GITHUB_API}/repos/{repo}/git/ref/heads/{branch}"
    resp = await client.get(url, headers=_headers())
    resp.raise_for_status()
    return resp.json()["object"]["sha"]


async def _create_branch(client: httpx.AsyncClient, repo: str, branch: str, sha: str) -> None:
    """Create a new branch pointing at *sha*."""
    url = f"{_GITHUB_API}/repos/{repo}/git/refs"
    resp = await client.post(
        url,
        headers=_headers(),
        json={"ref": f"refs/heads/{branch}", "sha": sha},
    )
    if resp.status_code == 422:
        # Branch already exists — acceptable (idempotent retry)
        logger.warning("Branch %s already exists — reusing", branch)
        return
    resp.raise_for_status()


async def _commit_file(
    client: httpx.AsyncClient,
    repo: str,
    branch: str,
    path: str,
    content: str,
    message: str,
    file_sha: str | None,
) -> str:
    """Create or update a file on *branch*. Returns the new commit SHA."""
    url = f"{_GITHUB_API}/repos/{repo}/contents/{path}"
    encoded = base64.b64encode(content.encode()).decode()
    payload: dict[str, Any] = {
        "message": message,
        "content": encoded,
        "branch": branch,
    }
    if file_sha:
        payload["sha"] = file_sha
    resp = await client.put(url, headers=_headers(), json=payload)
    resp.raise_for_status()
    return resp.json()["commit"]["sha"]


async def _create_pr(
    client: httpx.AsyncClient,
    repo: str,
    head: str,
    base: str,
    title: str,
    body: str,
) -> dict[str, Any]:
    """Open a pull request. Returns the PR object."""
    url = f"{_GITHUB_API}/repos/{repo}/pulls"
    resp = await client.post(
        url,
        headers=_headers(),
        json={
            "title": title,
            "head": head,
            "base": base,
            "body": body,
            "draft": GITHUB_PR_DRAFT,
        },
    )
    resp.raise_for_status()
    return resp.json()


async def _add_label(client: httpx.AsyncClient, repo: str, pr_number: int, label: str) -> None:
    """Add a label to a PR (creates the label if it doesn't exist)."""
    # Ensure label exists
    label_url = f"{_GITHUB_API}/repos/{repo}/labels"
    await client.post(
        label_url,
        headers=_headers(),
        json={"name": label, "color": "e11d48", "description": "LLM auto-heal fix"},
    )
    # Apply to PR
    issues_url = f"{_GITHUB_API}/repos/{repo}/issues/{pr_number}/labels"
    await client.post(issues_url, headers=_headers(), json={"labels": [label]})


# ── Patch application ─────────────────────────────────────────────────────────


def _apply_patch(original_content: str, original_snippet: str, fix_snippet: str) -> str:
    """
    Replace *original_snippet* with *fix_snippet* in *original_content*.

    Falls back to appending the fix as a comment block if the snippet
    is not found verbatim (e.g. the file has changed since the scan).
    """
    if original_snippet and original_snippet in original_content:
        return original_content.replace(original_snippet, fix_snippet, 1)

    # Snippet not found — append as a clearly marked block for manual review
    logger.warning("Auto-heal: original snippet not found verbatim — appending fix as comment block")
    separator = "\n\n" + "#" * 72 + "\n"
    note = (
        "# AUTO-HEAL FIX (snippet not found verbatim — apply manually)\n"
        "# Original snippet:\n"
        + textwrap.indent(original_snippet or "(not provided)", "# ")
        + "\n# Suggested fix:\n"
        + textwrap.indent(fix_snippet or "(not provided)", "# ")
        + "\n"
        + "#" * 72
        + "\n"
    )
    return original_content + separator + note


# ── PR body builder ───────────────────────────────────────────────────────────


def _build_pr_body(
    endpoint: str,
    file_path: str | None,
    original: str,
    fix: str,
    approved_by: str,
    ts: str,
) -> str:
    return textwrap.dedent(f"""\
        ## Auto-Heal Fix

        **Endpoint:** `{endpoint}`
        **File:** `{file_path or "unknown — apply manually"}`
        **Approved by:** {approved_by}
        **Generated at:** {ts}

        ### Vulnerability (original code)

        ```python
        {original}
        ```

        ### LLM Fix

        ```python
        {fix}
        ```

        ---

        > This PR was generated automatically by HOPEFXBrain auto-heal.
        > Review the diff carefully before merging. The LLM fix is a
        > starting point — validate against the full security context.

        **Checklist before merge:**
        - [ ] Fix does not introduce new vulnerabilities
        - [ ] Auth/rate-limit logic is correct
        - [ ] Tests pass (CI must be green)
        - [ ] Reviewed by a second engineer
    """)


# ── Public entry point ────────────────────────────────────────────────────────


class GitHubPRPublisher:
    """
    Publishes LLM-generated security fixes as GitHub Pull Requests.

    Usage::

        publisher = GitHubPRPublisher()
        result = await publisher.publish(
            endpoint="/api/auth/login",
            original_code="...",
            fix_code="...",
            approved_by="admin@hopefx.io",
        )
        logger.info(result["pr_url"])
    """

    async def publish(
        self,
        endpoint: str,
        original_code: str,
        fix_code: str,
        approved_by: str = "dashboard",
        fix_ts: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a branch, commit the fix, and open a GitHub PR.

        Returns a dict with keys:
          pr_url      — HTML URL of the opened PR
          pr_number   — PR number
          branch      — Branch name created
          file_path   — Source file patched (or None)
          status      — "created" | "error"
          error       — Error message (only present when status == "error")
        """
        if not GITHUB_TOKEN:
            return {
                "status": "error",
                "error": "GITHUB_TOKEN not configured — PR pipeline disabled",
            }

        ts_str = fix_ts or datetime.now(UTC).isoformat()
        slug = re.sub(r"[^a-z0-9]+", "-", endpoint.lower().strip("/"))[:40]
        ts_tag = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        branch_name = f"auto-heal/{ts_tag}-{slug}"

        file_path = _resolve_file_path(endpoint)

        try:
            repo = _repo()
        except RuntimeError as exc:
            logger.error("GitHub PR publisher repo config error: %s", exc)
            return {"status": "error", "error": "GitHub repository not configured — check server logs"}

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                # 1. Get base branch HEAD SHA
                base_sha = await _get_branch_sha(client, repo, GITHUB_BASE_BRANCH)

                # 2. Create feature branch
                await _create_branch(client, repo, branch_name, base_sha)

                # 3. Fetch current file content (if file path is known)
                file_sha: str | None = None
                patched_content: str

                if file_path:
                    file_data = await _get_file(client, repo, file_path)
                    if file_data:
                        raw_bytes = base64.b64decode(file_data["content"])
                        current_content = raw_bytes.decode("utf-8", errors="replace")
                        file_sha = file_data["sha"]
                        patched_content = _apply_patch(current_content, original_code, fix_code)
                    else:
                        # File not found on GitHub — create it with the fix
                        patched_content = fix_code
                        logger.warning(
                            "Auto-heal: %s not found on GitHub — creating new file",
                            file_path,
                        )
                else:
                    # No file mapping — create a standalone patch file
                    file_path = f"security/patches/{ts_tag}-{slug}.py"
                    patched_content = (
                        f"# Auto-heal patch for endpoint: {endpoint}\n# Generated: {ts_str}\n\n{fix_code}\n"
                    )

                # 4. Commit the patched file
                commit_message = (
                    f"fix(auto-heal): security patch for {endpoint}\n\n"
                    f"LLM-generated fix approved by {approved_by} at {ts_str}.\n"
                    f"Resolves vulnerability detected by HOPEFXBrain scan.\n\n"
                    f"Co-authored-by: HOPEFXBrain <no-reply@hopefx.io>"
                )
                await _commit_file(
                    client,
                    repo,
                    branch_name,
                    file_path,
                    patched_content,
                    commit_message,
                    file_sha,
                )

                # 5. Open PR
                pr_title = f"fix(auto-heal): security patch for {endpoint}"
                pr_body = _build_pr_body(endpoint, file_path, original_code, fix_code, approved_by, ts_str)
                pr = await _create_pr(client, repo, branch_name, GITHUB_BASE_BRANCH, pr_title, pr_body)

                # 6. Label the PR
                if GITHUB_PR_LABEL:
                    try:
                        await _add_label(client, repo, pr["number"], GITHUB_PR_LABEL)
                    except Exception as label_exc:
                        logger.debug("Failed to add PR label: %s", label_exc)

                logger.info(
                    "Auto-heal PR created: #%d %s branch=%s file=%s",
                    pr["number"],
                    pr["html_url"],
                    branch_name,
                    file_path,
                )

                return {
                    "status": "created",
                    "pr_url": pr["html_url"],
                    "pr_number": pr["number"],
                    "branch": branch_name,
                    "file_path": file_path,
                }

            except httpx.HTTPStatusError as exc:
                error_body = exc.response.text[:500]
                logger.error(
                    "Auto-heal PR failed: HTTP %d — %s",
                    exc.response.status_code,
                    error_body,
                )
                return {
                    "status": "error",
                    "error": f"GitHub API error {exc.response.status_code}: {error_body}",
                }
            except Exception:
                logger.exception("Auto-heal PR failed: %s")
                return {"status": "error", "error": "PR creation failed — check server logs"}


# ── Module-level singleton ────────────────────────────────────────────────────

_publisher: GitHubPRPublisher | None = None


def get_pr_publisher() -> GitHubPRPublisher:
    """Return the module-level GitHubPRPublisher singleton."""
    global _publisher
    if _publisher is None:
        _publisher = GitHubPRPublisher()
    return _publisher
