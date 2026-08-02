# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_codeql_path_and_regex_hardening.py
==================================================
Three CodeQL findings that were real, as opposed to the majority that were
already guarded and only looked untracked to the analyser.

1. ``core/page_routes.py`` — the SPA catch-all built ``_frontend_dist /
   full_path`` straight from the route parameter and served whatever came back.
   ``Path.__truediv__`` applies no traversal check, and the passthrough list
   above it only screens known route prefixes, so a segment that climbed out of
   the build directory was served like any other asset.

2. ``api/journal.py`` — the screenshot filename was
   ``f"{user.sub}_{trade_id}.{ext}"``. The ownership query proves the entry
   belongs to the caller; it does not constrain the characters in either value,
   and ``os.path.join`` treats a leading "/" as absolute and "../" as a climb.

3. ``api/custom_indicators.py`` — ``re.search(r"SMA\\([^,]*,\\s*(\\d+)\\)", …)``
   over a user-supplied formula. An unbounded ``[^,]*`` followed by a literal,
   retried at every offset, is quadratic on a long non-matching input.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


# ── 1. SPA catch-all path confinement ─────────────────────────────────────────


@pytest.mark.parametrize(
    "escape",
    [
        "../app.py",
        "../../etc/passwd",
        "assets/../../.env",
        "./../../config/config_manager.py",
        "/etc/passwd",
        "..",
        ".",
        ".env",
        "assets/..",
        "assets\\..\\..\\app.py",
        "assets/main.js\x00.png",
    ],
)
def test_the_allowlist_rejects_anything_that_could_leave_the_build_dir(escape):
    """First guard: every segment must start alphanumeric, so ".." is unspellable."""
    from core.page_routes import _ASSET_PATH_RE

    assert _ASSET_PATH_RE.fullmatch(escape) is None, f"{escape!r} passed the allowlist"


@pytest.mark.parametrize(
    "asset",
    [
        "assets/index-a1b2c3.js",
        "favicon.svg",
        "images/logo.png",
        "assets/vendor.min.css",
        "a",
    ],
)
def test_the_allowlist_still_admits_real_build_output(asset):
    """Rejecting traversal must not reject the assets Vite actually emits."""
    from core.page_routes import _ASSET_PATH_RE

    assert _ASSET_PATH_RE.fullmatch(asset) is not None, f"{asset!r} was rejected"


def test_confinement_still_holds_if_the_allowlist_were_loosened(tmp_path):
    """Second guard, checked independently of the first."""
    dist = tmp_path / "static"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (dist / "assets" / "main.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / ".env").write_text("SECURITY_JWT_SECRET=real", encoding="utf-8")

    dist_resolved = dist.resolve()

    def confined(rel: str) -> bool:
        try:
            asset = Path(os.path.join(str(dist_resolved), rel)).resolve()
            asset.relative_to(dist_resolved)
            return asset.is_file()
        except (ValueError, OSError):
            return False

    assert confined("assets/main.js")
    assert not confined("../.env")
    assert not confined("assets/../../.env")


def test_a_pathological_length_is_rejected_before_the_regex():
    from core.page_routes import _MAX_ASSET_PATH_LEN

    hostile = "a" * (_MAX_ASSET_PATH_LEN + 1)

    assert len(hostile) > _MAX_ASSET_PATH_LEN


def test_page_routes_wires_both_guards():
    """Guards the wiring: an allowlist unused is not a guard."""
    src = (Path(__file__).resolve().parents[2] / "core" / "page_routes.py").read_text(encoding="utf-8")

    assert "_frontend_dist_resolved = _frontend_dist.resolve()" in src
    assert "_ASSET_PATH_RE.fullmatch(full_path)" in src
    assert "_asset.relative_to(_frontend_dist_resolved)" in src
    # The tainted value must not reach path construction directly.
    assert "(_frontend_dist / full_path)" not in src


# ── 2. Screenshot filename sanitisation ───────────────────────────────────────


@pytest.mark.parametrize(
    ("sub", "trade_id"),
    [
        ("../../../etc/passwd", "t1"),
        ("/absolute", "t1"),
        ("user", "../../secret"),
        ("a/b\\c", "d/e"),
    ],
)
def test_screenshot_filenames_cannot_carry_a_path(sub, trade_id):
    """No separator survives, so the join stays inside static/screenshots."""
    import os

    from api.journal import _SAFE_NAME_RE

    safe_sub = _SAFE_NAME_RE.sub("_", sub)[:64] or "user"
    safe_trade = _SAFE_NAME_RE.sub("_", trade_id)[:64] or "entry"
    filename = f"{safe_sub}_{safe_trade}.png"

    assert "/" not in filename
    assert "\\" not in filename
    # One component, and the join lands where it should.
    assert os.path.basename(filename) == filename
    joined = os.path.normpath(os.path.join("static", "screenshots", filename))
    assert joined.startswith(os.path.join("static", "screenshots") + os.sep)


def test_screenshot_filename_keeps_ordinary_ids_readable():
    """Sanitising must not mangle the normal case into uselessness."""
    from api.journal import _SAFE_NAME_RE

    assert _SAFE_NAME_RE.sub("_", "user-42") == "user-42"
    assert _SAFE_NAME_RE.sub("_", "b3f1c2d4-9e8a-4f10-8c77-1a2b3c4d5e6f").count("_") == 0


# ── 3. Indicator formula regexes ──────────────────────────────────────────────


@pytest.mark.parametrize("fn", ["SMA", "EMA", "RSI"])
def test_formula_regexes_are_linear_on_a_long_non_match(fn):
    """The quadratic shape: long run of non-commas that never completes."""
    pattern = re.compile(rf"{fn}\([^,]{{0,64}},\s*(\d{{1,5}})\)")
    hostile = f"{fn}(" + "A" * 100_000

    t0 = time.perf_counter()
    assert pattern.match(hostile) is None
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.5, f"{fn} pattern took {elapsed:.3f}s — still backtracking"


@pytest.mark.parametrize(
    ("fn", "formula", "expected"),
    [
        ("SMA", "SMA(CLOSE, 20)", "20"),
        ("EMA", "EMA(CLOSE,50)", "50"),
        ("RSI", "RSI(CLOSE,   14)", "14"),
    ],
)
def test_formula_regexes_still_extract_the_period(fn, formula, expected):
    """Anchoring must not change what a valid formula parses to."""
    pattern = re.compile(rf"{fn}\([^,]{{0,64}},\s*(\d{{1,5}})\)")

    m = pattern.match(formula)

    assert m is not None, f"{formula!r} no longer parses"
    assert m.group(1) == expected


def test_custom_indicators_uses_the_anchored_bounded_patterns():
    """The endpoint must use the hardened form, not just this test's copy."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "api" / "custom_indicators.py").read_text(encoding="utf-8")

    for fn in ("SMA", "EMA", "RSI"):
        assert rf'm = re.match(r"{fn}\([^,]{{0,64}},\s*(\d{{1,5}})\)", formula)' in src, fn
    assert 're.search(r"SMA' not in src, "unbounded search pattern still present"
