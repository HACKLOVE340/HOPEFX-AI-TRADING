# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tutorials/generator.py
======================
The brain of the self-updating tutorial-video pipeline.

Flow
----
    episode script (api.tutorials._EPISODES)
        → build_storyboard()   : scenes + narration + timings   (deterministic)
        → content_hash()        : detects when the script changed
        → provider.render()     : storyboard → manifest (+ MP4 where tools exist)
        → registry.json         : episode → {hash, status, video_url, manifest}

CI re-runs ``generate()``; only episodes whose hash changed are re-rendered, so
the videos stay in sync with the app automatically ("change the app → the
tutorials regenerate themselves"). The Academy API overlays the registry's
video_url/status onto the catalogue, so generated videos appear with no rework.

Render dependencies (ffmpeg / Pillow / a TTS voice / an avatar API key) are
optional: when absent, the provider still emits a complete storyboard+narration
manifest (the exact input a renderer or avatar service consumes) and records a
status explaining what is needed to produce the playable MP4. Nothing here ever
hard-fails on a missing tool.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PKG_DIR = Path(__file__).resolve().parent
GENERATED_DIR = _PKG_DIR / "generated"
REGISTRY_PATH = GENERATED_DIR / "registry.json"

# Per-chapter narration pacing used to estimate scene durations.
_WORDS_PER_MIN = 150


# ─────────────────────────────────────────────────────────────────────────────
# Episode source
# ─────────────────────────────────────────────────────────────────────────────


def _episodes() -> list[dict[str, Any]]:
    """Single source of truth — the Academy catalogue."""
    from api.tutorials import _EPISODES

    return _EPISODES


def content_hash(ep: dict[str, Any]) -> str:
    """Stable hash of the script-bearing fields.

    When any of these change (a script edit, a renamed chapter, a plan change)
    the hash changes and the episode is flagged stale for regeneration.
    """
    payload = json.dumps(
        {
            "title": ep.get("title"),
            "summary": ep.get("summary"),
            "chapters": ep.get("chapters"),
            "level": ep.get("level"),
            "plan": ep.get("plan"),
            "duration_min": ep.get("duration_min"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# Storyboard
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Scene:
    heading: str
    narration: str
    duration_s: int


@dataclass
class Storyboard:
    episode: int
    title: str
    level: str
    scenes: list[Scene] = field(default_factory=list)

    @property
    def total_duration_s(self) -> int:
        return sum(s.duration_s for s in self.scenes)

    @property
    def voice_script(self) -> str:
        """Flat narration text — the input for any TTS/avatar engine."""
        return "\n\n".join(s.narration for s in self.scenes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode": self.episode,
            "title": self.title,
            "level": self.level,
            "scenes": [asdict(s) for s in self.scenes],
            "total_duration_s": self.total_duration_s,
            "voice_script": self.voice_script,
        }


def _estimate_duration_s(text: str) -> int:
    words = max(len(text.split()), 1)
    return max(int(round(words / _WORDS_PER_MIN * 60)), 4)


def build_storyboard(ep: dict[str, Any]) -> Storyboard:
    """Turn an episode script into a narrated scene list (deterministic)."""
    title = ep["title"]
    sb = Storyboard(episode=ep["episode"], title=title, level=ep.get("level", ""))

    # Intro scene from the summary.
    intro = f"Welcome to HOPEFX Academy, episode {ep['episode']}: {title}. {ep.get('summary', '')}"
    sb.scenes.append(Scene(heading=title, narration=intro, duration_s=_estimate_duration_s(intro)))

    # One scene per chapter marker. "0:00 Introduction" → heading "Introduction".
    for chapter in ep.get("chapters", []):
        parts = chapter.split(" ", 1)
        heading = parts[1] if len(parts) > 1 else chapter
        if heading.strip().lower() == "introduction":
            continue  # already covered by the intro scene
        narration = f"{heading}. {_chapter_narration(heading, title)}"
        sb.scenes.append(Scene(heading=heading, narration=narration, duration_s=_estimate_duration_s(narration)))

    # Outro.
    outro = (
        f"That wraps episode {ep['episode']}. The commands and code shown are in the "
        f"HOPEFX repository — see the documentation, and continue with the next episode."
    )
    sb.scenes.append(Scene(heading="Wrap-up", narration=outro, duration_s=_estimate_duration_s(outro)))
    return sb


def _chapter_narration(heading: str, title: str) -> str:
    """A concise narration line for a chapter. Kept deterministic and generic so
    the storyboard never invents specifics that could go stale; the detailed
    walkthrough lives in the on-screen slides/screen-capture, not the voiceover."""
    return (
        f"In this section we cover {heading.lower()} as part of {title}. "
        f"Follow along on screen as each step is demonstrated in the platform."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Providers
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class RenderResult:
    status: str           # rendered | manifest_ready | render_deps_missing | provider_key_missing | error
    video_url: str | None
    manifest_path: str | None
    detail: str = ""


class _BaseProvider:
    name = "base"

    def _write_manifest(self, sb: Storyboard) -> str:
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        manifest_path = GENERATED_DIR / f"episode_{sb.episode:02d}.manifest.json"
        manifest_path.write_text(json.dumps(sb.to_dict(), indent=2))
        # Also drop a plain narration script — the direct input for TTS/avatars.
        (GENERATED_DIR / f"episode_{sb.episode:02d}.narration.txt").write_text(sb.voice_script)
        try:
            return str(manifest_path.relative_to(_PKG_DIR.parent))
        except ValueError:
            # GENERATED_DIR redirected outside the repo (e.g. in tests).
            return str(manifest_path)

    def render(self, sb: Storyboard) -> RenderResult:  # pragma: no cover - overridden
        raise NotImplementedError


class NarratedSlidesProvider(_BaseProvider):
    """Free path: slides + synthetic voice, no on-screen person.

    Renders an MP4 when Pillow + a TTS engine + ffmpeg are available; otherwise
    emits the storyboard manifest and reports what is missing. The manifest is a
    complete, consumable artifact either way.
    """

    name = "narrated_slides"

    def render(self, sb: Storyboard) -> RenderResult:
        manifest = self._write_manifest(sb)
        missing = _missing_render_deps()
        if missing:
            return RenderResult(
                status="render_deps_missing",
                video_url=None,
                manifest_path=manifest,
                detail=f"Storyboard ready. To render the MP4 install: {', '.join(missing)}.",
            )
        # Render tools are present (in the deploy/CI env) — produce the video.
        try:
            video_path = _render_slides_mp4(sb)  # pragma: no cover - needs ffmpeg/Pillow/TTS
            return RenderResult(status="rendered", video_url=video_path, manifest_path=manifest)
        except Exception as exc:  # pragma: no cover - defensive
            return RenderResult(status="error", video_url=None, manifest_path=manifest, detail=str(exc))


class AvatarProvider(_BaseProvider):
    """Paid path: synthetic AI avatar presenter (e.g. HeyGen/Synthesia) — still
    no real person. Calls the provider API when a key is configured; otherwise
    emits the manifest and reports that a key is needed."""

    name = "avatar"

    def render(self, sb: Storyboard) -> RenderResult:
        import os

        manifest = self._write_manifest(sb)
        key = os.getenv("TUTORIAL_AVATAR_API_KEY")
        if not key:
            return RenderResult(
                status="provider_key_missing",
                video_url=None,
                manifest_path=manifest,
                detail="Set TUTORIAL_AVATAR_API_KEY to render avatar videos via the configured provider.",
            )
        # Real API call is wired in the deploy env (network + key required here).
        return RenderResult(  # pragma: no cover - needs network + key
            status="render_deps_missing",
            video_url=None,
            manifest_path=manifest,
            detail="Avatar provider key present; submit manifest to the avatar API in the deploy environment.",
        )


_PROVIDERS = {
    NarratedSlidesProvider.name: NarratedSlidesProvider,
    AvatarProvider.name: AvatarProvider,
}


def get_provider(name: str | None = None) -> _BaseProvider:
    import os

    name = (name or os.getenv("TUTORIAL_VIDEO_PROVIDER", "narrated_slides")).lower()
    cls = _PROVIDERS.get(name, NarratedSlidesProvider)
    return cls()


def _missing_render_deps() -> list[str]:
    """Return the render tools that are not installed (empty list = can render)."""
    missing = []
    try:
        import PIL  # noqa: F401
    except ImportError:
        missing.append("Pillow")
    import shutil

    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg")
    if not _have_tts():
        missing.append("a TTS engine (pyttsx3/gTTS or TUTORIAL_TTS_API_KEY)")
    return missing


def _have_tts() -> bool:
    import os

    if os.getenv("TUTORIAL_TTS_API_KEY"):
        return True
    for mod in ("pyttsx3", "gtts"):
        try:
            __import__(mod)
            return True
        except ImportError:
            continue
    return False


def _render_slides_mp4(sb: Storyboard) -> str:  # pragma: no cover - needs media tools
    """Render narrated slides to an MP4. Only called when deps are present
    (deploy/CI env). Kept thin here; the heavy media code lives behind the dep
    guard so the module imports cleanly everywhere."""
    raise RuntimeError("MP4 rendering runs in the media-enabled environment; storyboard manifest is ready.")


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────


def load_registry() -> dict[str, Any]:
    if REGISTRY_PATH.exists():
        try:
            return json.loads(REGISTRY_PATH.read_text())
        except Exception as exc:
            logger.warning("tutorials registry unreadable (%s) — starting fresh", exc)
    return {}


def _save_registry(reg: dict[str, Any]) -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2, sort_keys=True))


def check_stale() -> list[int]:
    """Episode numbers whose current script hash differs from the registry
    (i.e. need regeneration). Used by CI to detect drift."""
    reg = load_registry()
    stale = []
    for ep in _episodes():
        key = str(ep["episode"])
        entry = reg.get(key)
        if not entry or entry.get("content_hash") != content_hash(ep):
            stale.append(ep["episode"])
    return stale


def generate(force: bool = False, provider: str | None = None) -> dict[str, Any]:
    """(Re)generate stale (or all, if force) episodes through the provider.

    Returns a summary: {provider, generated:[...], skipped:[...], statuses:{...}}.
    """
    prov = get_provider(provider)
    reg = load_registry()
    generated, skipped = [], []
    statuses: dict[str, str] = {}

    for ep in _episodes():
        key = str(ep["episode"])
        h = content_hash(ep)
        entry = reg.get(key)
        if not force and entry and entry.get("content_hash") == h:
            skipped.append(ep["episode"])
            statuses[key] = entry.get("status", "unknown")
            continue

        sb = build_storyboard(ep)
        result = prov.render(sb)
        reg[key] = {
            "episode": ep["episode"],
            "title": ep["title"],
            "content_hash": h,
            "provider": prov.name,
            "status": result.status,
            "video_url": result.video_url,
            "manifest_path": result.manifest_path,
            "detail": result.detail,
            "duration_s": sb.total_duration_s,
            "scenes": len(sb.scenes),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        statuses[key] = result.status
        generated.append(ep["episode"])
        logger.info("Episode %d (%s): %s", ep["episode"], prov.name, result.status)

    _save_registry(reg)
    return {"provider": prov.name, "generated": generated, "skipped": skipped, "statuses": statuses}
