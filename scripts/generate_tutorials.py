#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/generate_tutorials.py
=============================
CLI for the self-updating tutorial-video pipeline (tutorials/generator.py).

    # regenerate only episodes whose script changed (the normal/CI run)
    python scripts/generate_tutorials.py

    # force-regenerate everything (e.g. after a template change)
    python scripts/generate_tutorials.py --force

    # CI drift check: exit 1 if any episode is stale (used to require regen)
    python scripts/generate_tutorials.py --check

    # choose a provider (default: env TUTORIAL_VIDEO_PROVIDER or narrated_slides)
    python scripts/generate_tutorials.py --provider avatar

The free narrated-slides provider renders an MP4 where Pillow + ffmpeg + a TTS
voice are available, and otherwise emits a complete storyboard/narration manifest
(the input an avatar service or renderer consumes). Avatar/premium voices are
opt-in via TUTORIAL_VIDEO_PROVIDER + the relevant API key.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tutorials.generator import check_stale, generate


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Generate/refresh HOPEFX Academy tutorial videos")
    ap.add_argument("--check", action="store_true", help="exit 1 if any episode is stale (CI drift check)")
    ap.add_argument("--force", action="store_true", help="regenerate every episode, not just stale ones")
    ap.add_argument("--provider", default=None, help="video provider (narrated_slides | avatar)")
    args = ap.parse_args()

    if args.check:
        stale = check_stale()
        if stale:
            print(f"STALE — {len(stale)} episode(s) need regeneration: {stale}")
            print("Run: python scripts/generate_tutorials.py")
            return 1
        print("All tutorial videos are up to date with their scripts.")
        return 0

    summary = generate(force=args.force, provider=args.provider)
    print("=" * 60)
    print(f"Tutorial generation — provider: {summary['provider']}")
    print(f"  generated: {summary['generated'] or 'none'}")
    print(f"  skipped (unchanged): {len(summary['skipped'])}")
    # Status breakdown
    counts: dict[str, int] = {}
    for st in summary["statuses"].values():
        counts[st] = counts.get(st, 0) + 1
    for st, n in sorted(counts.items()):
        print(f"  {st}: {n}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
