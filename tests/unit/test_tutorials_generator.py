# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_tutorials_generator.py
=======================================
Tests the self-updating tutorial-video generator (tutorials/generator.py).

The render tools (ffmpeg/Pillow/TTS) aren't in CI, so these tests exercise the
deterministic brain: storyboard building, the content-hash self-update loop,
the registry, and the provider selection/status. Output is redirected to a tmp
dir so the committed manifests are never touched.
"""

from __future__ import annotations

import pytest

import tutorials.generator as gen


@pytest.fixture(autouse=True)
def _isolated_output(tmp_path, monkeypatch):
    monkeypatch.setattr(gen, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setattr(gen, "REGISTRY_PATH", tmp_path / "generated" / "registry.json")
    yield


def _sample_ep() -> dict:
    return {
        "episode": 99,
        "title": "Test Episode",
        "level": "Beginner",
        "duration_min": 10,
        "plan": "free",
        "status": "script_ready",
        "summary": "A test of the generator.",
        "chapters": ["0:00 Introduction", "2:00 First topic", "5:00 Second topic"],
        "thumbnail_text": "Test",
        "video_url": None,
    }


def test_content_hash_changes_on_script_edit() -> None:
    ep = _sample_ep()
    h1 = gen.content_hash(ep)
    ep["summary"] = "A different summary."
    assert gen.content_hash(ep) != h1
    # Stable for identical input.
    assert gen.content_hash(_sample_ep()) == gen.content_hash(_sample_ep())


def test_build_storyboard_has_scenes_and_narration() -> None:
    sb = gen.build_storyboard(_sample_ep())
    headings = [s.heading for s in sb.scenes]
    assert sb.scenes[0].heading == "Test Episode"      # intro
    assert "First topic" in headings and "Second topic" in headings
    assert "Wrap-up" in headings                        # outro
    # The duplicate "Introduction" chapter is folded into the intro scene.
    assert headings.count("Introduction") == 0
    assert sb.total_duration_s > 0
    assert sb.voice_script.strip()


def test_provider_selection() -> None:
    assert gen.get_provider("narrated_slides").name == "narrated_slides"
    assert gen.get_provider("avatar").name == "avatar"
    assert gen.get_provider("unknown").name == "narrated_slides"  # safe default


def test_generate_creates_registry_and_is_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(gen, "_episodes", lambda: [_sample_ep()])

    first = gen.generate()
    assert first["generated"] == [99]
    reg = gen.load_registry()
    assert "99" in reg
    # No render tools in CI → storyboard manifest is still produced.
    assert reg["99"]["status"] in ("render_deps_missing", "rendered", "manifest_ready")
    assert reg["99"]["scenes"] > 0
    assert (gen.GENERATED_DIR / "episode_99.manifest.json").exists()
    assert (gen.GENERATED_DIR / "episode_99.narration.txt").exists()

    # Re-run with no script change → nothing regenerated.
    second = gen.generate()
    assert second["generated"] == []
    assert second["skipped"] == [99]


def test_check_stale_detects_drift(monkeypatch) -> None:
    ep = _sample_ep()
    monkeypatch.setattr(gen, "_episodes", lambda: [ep])

    assert gen.check_stale() == [99]      # nothing generated yet
    gen.generate()
    assert gen.check_stale() == []        # now in sync

    ep["chapters"] = ep["chapters"] + ["8:00 New topic"]  # app/script changed
    assert gen.check_stale() == [99]      # drift detected → would regenerate


def test_force_regenerates_unchanged(monkeypatch) -> None:
    monkeypatch.setattr(gen, "_episodes", lambda: [_sample_ep()])
    gen.generate()
    assert gen.generate(force=True)["generated"] == [99]
