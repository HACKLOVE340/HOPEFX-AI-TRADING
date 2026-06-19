# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tutorials package
=================
Self-updating AI tutorial-video generation.

Turns the episode scripts (single source of truth: api.tutorials._EPISODES) into
per-episode storyboards + narration, tracks a content hash so videos regenerate
only when the underlying script/app surface changes, and renders them through a
pluggable provider (free narrated-slides by default; avatar/premium opt-in).

Public surface:
    from tutorials.generator import generate, check_stale, load_registry
"""

from tutorials.generator import (  # noqa: F401
    REGISTRY_PATH,
    build_storyboard,
    check_stale,
    content_hash,
    generate,
    load_registry,
)
