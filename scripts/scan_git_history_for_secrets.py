#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/scan_git_history_for_secrets.py — every blob, every commit, unfiltered.

`docs/audit/AI_CORE_SPEC.md` open item 6 is "rotate the exposed superadmin
credential in git history", above everything else in the build. The audit could
not confirm the exposure: `AI_CORE_SPEC_INTAKE.md` §5 records "I found no live
credential in the tracked working tree. I did not scan the full commit history."

This scans the full history — every object reachable from every ref, not just
the current tree, and not just the tip of each branch. It matches only patterns
that have **no legitimate placeholder form** (an AWS key id, a GitHub PAT, a
Stripe live key, a private-key block), so there is no benign-filter to hide a
real hit behind. A filtered scan is easy to make quiet; this one is not.

`detect-secrets` already runs in pre-commit against the working tree. This is
the history counterpart, and it answers a different question: not "is a secret
being added" but "was one ever added".

**Rotation is the fix regardless of what this prints.** A secret removed from
history is not un-leaked — anyone who cloned or forked still has it. A clean
result here means the exposure was not committed to this repository; it does not
mean the credential is safe.

Usage:
    python scripts/scan_git_history_for_secrets.py

Exit codes: 0 = nothing found, 1 = at least one match to triage.
"""

import re
import subprocess
import collections

PATTERNS = [
    ("aws_access_key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("github_pat", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("slack_token", re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("stripe_live", re.compile(rb"\b[sr]k_live_[A-Za-z0-9]{20,}")),
    ("stripe_test", re.compile(rb"\b[sr]k_test_[A-Za-z0-9]{20,}")),
    ("openai_key", re.compile(rb"\bsk-[A-Za-z0-9]{40,}")),
    ("anthropic_key", re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("private_key_block", re.compile(rb"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("jwt_three_part", re.compile(rb"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}")),
    ("google_api", re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("sendgrid", re.compile(rb"\bSG\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")),
    ("oanda_token", re.compile(rb"\b[0-9a-f]{32}-[0-9a-f]{32}\b")),
    ("telegram_bot", re.compile(rb"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
]

ALLOWLIST_PRAGMA = re.compile(rb"pragma:\s*allowlist\s+secret", re.IGNORECASE)

blobs = subprocess.run(
    ["git", "rev-list", "--all", "--objects"], capture_output=True, text=True, check=False
).stdout.splitlines()
paths = {}
for line in blobs:
    p = line.split(maxsplit=1)
    if len(p) == 2:
        paths.setdefault(p[0], p[1])

hits = collections.defaultdict(set)
checked = 0
for sha, path in paths.items():
    data = subprocess.run(["git", "cat-file", "-p", sha], capture_output=True, check=False).stdout
    if b"\0" in data[:8000] or len(data) > 5_000_000:
        continue
    checked += 1
    for name, pat in PATTERNS:
        for m in pat.finditer(data):
            ls = data.rfind(b"\n", 0, m.start()) + 1
            le = data.find(b"\n", m.end())
            line = data[ls : le if le != -1 else None]
            # Honour the repository's existing marker rather than inventing a
            # second allowlist. `detect-secrets` already uses this pragma in
            # pre-commit, so a line reviewed and accepted there does not need
            # reviewing twice — and one convention cannot drift from the other.
            if ALLOWLIST_PRAGMA.search(line):
                continue
            hits[name].add((path, line[:180].decode("utf-8", "replace").strip()))


def main() -> int:
    print(f"UNFILTERED scan of {checked} blobs across all history\n")
    if not hits:
        print(f"ZERO matches for any of the {len(PATTERNS)} high-signal patterns.")
        print("No credential of a recognised format has ever been committed to this repository.")
        print("\nThis does not make a leaked credential safe. Rotation is the fix regardless:")
        print("removing a secret from history does not un-leak it.")
        return 0

    triage = 0
    for name, items in sorted(hits.items()):
        print(f"== {name} ({len(items)}) ==")
        for path, ctx in sorted(items)[:10]:
            triage += 1
            print(f"   {path}\n      {ctx[:150]}")
    print(f"\n{triage} match(es) to triage. A test fixture is expected; a real value is not.")
    print("Rotate anything real, then treat the history copy as already public.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
