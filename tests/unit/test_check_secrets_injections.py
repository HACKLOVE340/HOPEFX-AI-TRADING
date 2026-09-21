# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`scripts/check_secrets.sh` — the hook that stops credentials being committed.

It had no test. A secret scanner that cannot fail is the worst kind of dead
control: it produces a green tick over every commit that leaks a key.

Injecting into it found a real bypass. The placeholder allowlist was matched
against the **whole line** as a substring, so a genuine credential containing
`xxx`, `none`, `null` or `tbd` anywhere in it was silently skipped:

    API_KEY: "Sxxx7QZR2WN4TBVKD9jj"       # contains 'xxx'      -> skipped  # pragma: allowlist secret
    DB_PASSWORD: "nonextradinghunter22"   # contains 'none'     -> skipped  # pragma: allowlist secret

Both were verified to pass the old script. The match is now anchored to the
parsed value for those short ambiguous tokens, while long unambiguous ones
(`placeholder`, `example`, `changeme`, `your-`) stay substring matches because
they do not occur inside real credentials by accident.

## Scope, pinned deliberately

This script is the **config-format specialist** — yaml, env, ini, cfg, conf. It
excludes `.py`, `.ts`, `.js` and `.sh` by design, and `detect-secrets` covers
those (verified: it flags a `.py` credential as both `Secret Keyword` and
`Hex High Entropy String`). The division is only safe while both hooks exist,
so `test_source_files_are_deliberately_out_of_scope` records it — a reader who
removes the detect-secrets hook believing this script covers source code would
open a hole neither one closes.

Every case runs in a throwaway git repository. Staging a credential into the
real repository to test a secret scanner would be a poor way to find out the
scanner works.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 — runs the script under test, fixed argument lists
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "check_secrets.sh"


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A git repository with history, which is what pre-commit runs against."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, root / "scripts" / SCRIPT.name)
    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "test")
    (root / "README").write_text("seed\n", encoding="utf-8")
    _git(root, "add", "README")
    _git(root, "commit", "-qm", "init")
    return root


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — fixed argument list, no shell
        ["git", *args], cwd=root, capture_output=True, text=True, check=False
    )


def _blocks(root: Path, filename: str, line: str) -> bool:
    """Does the scanner block this line, staged in this file?"""
    path = root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(line + "\n", encoding="utf-8")
    _git(root, "add", filename)
    result = subprocess.run(  # nosec B603 — fixed argument list, no shell
        ["bash", "scripts/check_secrets.sh"], cwd=root, capture_output=True, text=True, check=False
    )
    _git(root, "rm", "-q", "--cached", filename)
    path.unlink()
    return result.returncode != 0


#: Contains no allowlisted token, in any casing. Verified against the allowlist
#: rather than assumed — the first version of these tests used a value
#: containing "EXAMPLE" and was skipped by the scanner, which would have made
#: every assertion below pass for the wrong reason.
SECRET = "9f2b7c1ade4856bd3fa0c7e12b98d4a6"  # pragma: allowlist secret


class TestTheFixtureIsNotSelfDefeating:
    def test_the_test_secret_trips_no_allowlist_rule(self) -> None:
        lowered = SECRET.lower()
        for token in ("example", "changeme", "placeholder", "your-", "your_", "xxx", "tbd", "none", "null"):
            assert token not in lowered, f"the test secret contains {token!r} and would be allowlisted"


class TestItBlocksRealCredentials:
    @pytest.mark.parametrize(
        ("filename", "line"),
        [
            ("config.yaml", f'API_KEY: "{SECRET}"'),
            ("config.yml", f"API_SECRET: {SECRET}"),
            ("prod.env", f"DB_PASSWORD={SECRET}"),
            ("app.ini", f"JWT_SECRET = {SECRET}"),
            ("app.cfg", f"ACCESS_TOKEN={SECRET}"),
            ("nested/deep/svc.yaml", f'CLIENT_SECRET: "{SECRET}"'),
        ],
    )
    def test_a_credential_in_a_config_file_is_blocked(self, sandbox: Path, filename: str, line: str) -> None:
        assert _blocks(sandbox, filename, line), f"{filename} was not blocked"

    def test_a_clean_config_file_is_not_blocked(self, sandbox: Path) -> None:
        # The positive control. Every assertion above passes against a script
        # that blocks unconditionally.
        assert not _blocks(sandbox, "clean.yaml", "timeout_seconds: 30")


class TestTheBypassThatWasFound:
    """The placeholder allowlist matched the whole line as a substring, so a
    real credential containing a short token anywhere in it was skipped."""

    @pytest.mark.parametrize(
        "line",
        [
            'API_KEY: "Sxxx7QZR2WN4TBVKD9jj"',  # pragma: allowlist secret
            'DB_PASSWORD: "nonextradinghunter22"',  # pragma: allowlist secret
            'JWT_SECRET: "nullifyR2WN4TBVKD9jj"',  # pragma: allowlist secret
            'AUTH_TOKEN: "tbdR2WN4TBVKD9jjQ7Zx"',
        ],
    )
    def test_a_real_credential_containing_an_allowlisted_token_is_blocked(self, sandbox: Path, line: str) -> None:
        assert _blocks(sandbox, "config.yaml", line), f"bypass still open: {line}"


class TestTheDocumentedSkipsStillSkip:
    """The other half of Rule 1. A scanner that blocks everything is not a
    working control either — it just gets disabled."""

    @pytest.mark.parametrize(
        "line",
        [
            f'API_KEY: "{SECRET}"  # pragma: allowlist secret',
            "API_KEY: ${OANDA_API_KEY}",
            "API_KEY: $OANDA_API_KEY",
            "API_KEY: ${{ secrets.OANDA_API_KEY }}",
            'API_KEY: "changeme"',  # pragma: allowlist secret
            'API_KEY: "your-key-here"',  # pragma: allowlist secret
            'API_KEY: "ci-placeholder"',  # pragma: allowlist secret
            'API_KEY: "<BASE64_ENCODED_KEY>"',
            'API_KEY: ""',
            'API_KEY: "xxxxx"',  # pragma: allowlist secret
            'API_KEY: "TBD"',  # pragma: allowlist secret
            "  password:\n    secretKeyRef:",
            f"# API_KEY: {SECRET}",
        ],
    )
    def test_a_safe_line_is_not_blocked(self, sandbox: Path, line: str) -> None:
        assert not _blocks(sandbox, "config.yaml", line), f"false positive: {line}"


class TestScopeIsRecordedRatherThanAssumed:
    def test_source_files_are_deliberately_out_of_scope(self, sandbox: Path) -> None:
        """`.py`, `.ts` and `.sh` are excluded here and covered by detect-secrets.

        Pinned so the division of labour is visible. If this ever starts
        blocking, the exclusion list changed and the detect-secrets overlap
        should be re-checked; if detect-secrets is ever removed, this test is
        the record of what it was carrying.
        """
        for filename, line in (
            ("settings.py", f'API_KEY = "{SECRET}"'),
            ("app.ts", f'const API_KEY = "{SECRET}";'),
            ("deploy.sh", f'ACCESS_TOKEN="{SECRET}"'),
        ):
            assert not _blocks(sandbox, filename, line), (
                f"{filename} is now blocked by check_secrets.sh — the exclusion list changed. "
                "Confirm detect-secrets still covers source files before relying on either."
            )

    def test_the_detect_secrets_hook_is_still_configured(self) -> None:
        # The other half of the division. If this hook goes, source files are
        # covered by nothing.
        config = (REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        assert "detect-secrets" in config, (
            "detect-secrets is gone, and check_secrets.sh excludes .py/.ts/.js/.sh — "
            "source-code credentials would now be scanned by nothing."
        )
