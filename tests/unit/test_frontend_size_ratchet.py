# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The size ratchet must be able to refuse.

Rule 1 of this repository: a control that cannot fail is not a control, and a
ratchet is the easiest kind to get that wrong — it passes on a healthy tree,
which is exactly what a broken measurement also does.

So every refusal is driven against a real throwaway tree rather than asserted
from reading the source, and the last test is the sanity floor: a glob that
stops matching reports zero findings, and zero findings from a ratchet is
indistinguishable from success unless something asserts it scanned a tree at
all.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "frontend_size_ratchet.py"


def _load():
    spec = importlib.util.spec_from_file_location("size_ratchet", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "frontend" / "src"
    for rel, body in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path


# Two unreachable sizes: one inline fontSize, one numeric spacing utility.
TWO = 'export default () => <div className="p-4" style={{ fontSize: 12 }} />;\n'
ONE = 'export default () => <div className="p-4" />;\n'
NONE = 'export default () => <div className="p-card" style={{ fontSize: "var(--fs-body)" }} />;\n'


def test_it_counts_both_populations(tmp_path):
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": TWO})
    assert mod.count_sizes(root) == {"frontend/src/pages/A.tsx": 2}


def test_a_token_reading_page_is_not_debt(tmp_path):
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": NONE})
    assert mod.count_sizes(root) == {}


def test_a_count_that_rose_blocks(tmp_path, capsys):
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": ONE})
    assert mod.adopt(root) == 0
    (root / "frontend" / "src" / "pages" / "A.tsx").write_text(TWO, encoding="utf-8")
    assert mod.check(root) == 1
    assert "up from 1" in capsys.readouterr().err


def test_a_new_file_with_any_size_blocks(tmp_path, capsys):
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": ONE})
    assert mod.adopt(root) == 0
    (root / "frontend" / "src" / "pages" / "B.tsx").write_text(TWO, encoding="utf-8")
    assert mod.check(root) == 1
    assert "no baseline entry" in capsys.readouterr().err


def test_a_file_that_reached_zero_must_leave_the_record(tmp_path, capsys):
    """The half a ratchet usually gets wrong. An entry left at 0 is a standing
    permission to add two sizes back without anything noticing."""
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": TWO})
    assert mod.adopt(root) == 0
    (root / "frontend" / "src" / "pages" / "A.tsx").write_text(NONE, encoding="utf-8")
    assert mod.check(root) == 1
    assert "must leave the record" in capsys.readouterr().err


def test_a_deleted_file_simply_leaves(tmp_path):
    """Progress, not a violation — and the reason the check above tests for the
    file's EXISTENCE rather than only for its absence from the counts."""
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": TWO, "pages/B.tsx": ONE})
    assert mod.adopt(root) == 0
    (root / "frontend" / "src" / "pages" / "A.tsx").unlink()
    assert mod.check(root) == 0


def test_an_unchanged_tree_passes(tmp_path):
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": TWO})
    assert mod.adopt(root) == 0
    assert mod.check(root) == 0


def test_a_fall_is_reported_but_does_not_block(tmp_path, capsys):
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": TWO})
    assert mod.adopt(root) == 0
    (root / "frontend" / "src" / "pages" / "A.tsx").write_text(ONE, encoding="utf-8")
    assert mod.check(root) == 0
    assert "run --adopt to bank the progress" in capsys.readouterr().out


def test_a_missing_baseline_blocks_rather_than_passing(tmp_path):
    """The failure mode that matters most: no baseline must not read as clean."""
    mod = _load()
    root = _tree(tmp_path, {"pages/A.tsx": TWO})
    assert mod.check(root) == 1


def test_an_empty_tree_with_no_baseline_blocks(tmp_path, capsys):
    """This test exists because an injection survived without it.

    Removing the `if not baseline` guard left all ten other tests green: with a
    populated tree every file then failed as "no baseline entry", so the check
    still returned 1 and nothing noticed. The guard's real job is the case those
    tests never reach — nothing scanned AND nothing recorded, where the loops
    below have no work and the function falls through to `return 0`. A moved or
    renamed `frontend/src` reads exactly like a clean tree, which is how a gate
    stops being one.
    """
    mod = _load()
    root = tmp_path  # no frontend/src at all
    assert mod.count_sizes(root) == {}
    assert mod.check(root) == 1
    assert "no baseline" in capsys.readouterr().err


def test_the_register_and_the_ratchet_count_the_same_population():
    """One counter, not two. The probe in correction_register.py imports
    `count_split` from here; if that import is ever replaced by a second set of
    regexes, these two numbers are free to drift apart."""
    mod = _load()
    _tokens, sizes, space = mod.count_split(REPO)
    assert sizes + space == sum(mod.count_sizes(REPO).values())


def test_the_committed_baseline_still_describes_the_tree():
    """The sanity floor, against the repository itself."""
    mod = _load()
    counts = mod.count_sizes(REPO)
    assert len(counts) > 50, "the scan stopped finding the frontend"
    baseline = json.loads((REPO / mod.BASELINE_REL).read_text(encoding="utf-8"))
    assert baseline["_total"] == sum(baseline["files"].values())
    assert mod.check(REPO) == 0


# ── the display band ─────────────────────────────────────────────────────────
#
# Everything at or above 28px is beyond the type scale: `--fs-hero` is 26px at
# `ultra`, which is the tier `densityPref.ts` gives a person by default and the
# tier `frontend_size_codemod.py` is anchored to. So no token can reach these
# sites, and the obvious next move is to extend the scale with a `--fs-display`
# tier and convert them.
#
# That move is wrong for most of them, and only a measurement says so: the
# majority are sizing an EMOJI, where `fontSize` is the only lever a glyph has.
# Every one of those disappears when `frontend_emoji_ratchet` does its job and
# the emoji becomes an SVG sized by `width`/`height`. Minting design-system API
# for debt that is scheduled for deletion is how a token outlives its reason.
#
# So the band is classified rather than counted, and these tests hold the
# classifier — not the ratio, which is supposed to move.


def test_the_band_starts_above_the_scale(tmp_path):
    mod = _load()
    assert mod.DISPLAY_FLOOR == 28
    root = _tree(tmp_path, {"a.tsx": "<p style={{ fontSize: 26 }}>x</p>\n<p style={{ fontSize: 28 }}>y</p>\n"})
    band = mod.display_band(root)
    assert [s.px for s in band] == [28]


def test_an_emoji_is_classified_as_a_glyph(tmp_path):
    mod = _load()
    root = _tree(tmp_path, {"a.tsx": "<div style={{ fontSize: 32 }}>\U0001f4cb</div>\n"})
    assert [s.kind for s in mod.display_band(root)] == ["glyph"]


def test_a_heading_is_classified_as_type(tmp_path):
    mod = _load()
    root = _tree(tmp_path, {"a.tsx": "  title: { fontSize: 36, fontWeight: 800 },\n"})
    assert [s.kind for s in mod.display_band(root)] == ["type"]


def test_the_glyph_test_reaches_outside_the_emoji_block():
    """Half the glyphs in this tree are not in the emoji block at all.

    `⏳` is Miscellaneous Technical, `☢` and `✅` are Miscellaneous
    Symbols, `⭐` is Miscellaneous Symbols and Arrows. A classifier that
    only knew U+1F000-U+1FAFF would call four of the biggest sites `type` and
    argue for a token none of them needs.
    """
    mod = _load()
    for glyph in ("⏳", "☢️", "⚠️", "✅", "⭐", "\U0001f6e1️"):
        assert mod._classify(f"<div style={{{{ fontSize: 48 }}}}>{glyph}</div>") == "glyph", glyph


def test_an_arrow_or_a_sign_is_not_a_glyph():
    """The wide sweep that catches `⭐` also catches `→` and `×`, which are text.

    Widening the range until every emoji matched would classify a heading that
    contains an arrow as a glyph, and the whole point of the split is that the
    `type` side is the side that might deserve a token.
    """
    mod = _load()
    for ch in ("→", "×", "±", "—", "…"):
        assert mod._classify(f"  title: {{ fontSize: 36 }},  // {ch}") == "type", ch


def test_a_size_inside_a_chart_option_is_still_counted(tmp_path):
    """The band is a measurement, not a codemod — it counts what it cannot fix.

    `frontend_size_codemod.py` refuses a canvas file because `var()` is resolved
    by the cascade and a canvas is not the cascade. That is a reason not to
    REWRITE the site; it is not a reason to pretend the density control reaches
    it.
    """
    mod = _load()
    root = _tree(tmp_path, {"a.tsx": "createChart(el, { layout: { fontSize: 32 } });\n"})
    assert len(mod.display_band(root)) == 1


def test_the_split_sums_to_the_band(tmp_path):
    mod = _load()
    root = _tree(
        tmp_path,
        {
            "a.tsx": "<div style={{ fontSize: 32 }}>\U0001f4cb</div>\n",
            "b.tsx": "  title: { fontSize: 36 },\n  metric: { fontSize: 48 },\n",
        },
    )
    split = mod.display_split(root)
    assert split == {"glyph": 1, "type": 2}
    assert sum(split.values()) == len(mod.display_band(root))


def test_the_live_tree_has_a_display_band_at_all():
    """The sanity floor, same as the one above: a classifier that matched
    nothing would report a clean split and agree with every conclusion.

    It asserted `{"glyph", "type"}` until the eleven typographic sites were
    converted, at which point the live tree stopped containing a `type` site and
    a passing test went red for the fix working. That assertion was never the
    floor — that BOTH outcomes are reachable is proved by the fixtures above,
    where they can be constructed. What this holds is that the scan ran.
    """
    mod = _load()
    band = mod.display_band(REPO)
    assert len(band) >= 20
    assert {s.kind for s in band} <= {"glyph", "type"}
    assert band, "the display band is empty — the scan matched nothing"


# ── prose is not debt ────────────────────────────────────────────────────────


def test_a_size_in_a_comment_is_not_counted(tmp_path):
    """F255/F257 in the size dimension: a scanner that reads prose as source.

    A file that explains the literal it removed would keep its baseline line
    forever, because there is nothing left to convert.
    """
    mod = _load()
    root = _tree(
        tmp_path,
        {
            "a.tsx": "// it used to be fontSize: 32 in p-4\n"
            " * and the block-comment form: fontSize: 40, gap-3\n"
            "<p style={{ fontSize: 13 }}>x</p>\n",
        },
    )
    assert mod.count_sizes(root) == {"frontend/src/a.tsx": 1}
    assert mod.count_split(root)[1] == 1


def test_a_trailing_comment_does_not_excuse_the_code_on_its_line(tmp_path):
    """Only a line that OPENS with a comment is prose. `fontSize: 32, // why`
    is a literal with an explanation, and the literal is still unreachable."""
    mod = _load()
    root = _tree(tmp_path, {"a.tsx": "  title: { fontSize: 32 },  // the page heading\n"})
    assert mod.count_sizes(root) == {"frontend/src/a.tsx": 1}


def test_the_display_band_skips_prose_too(tmp_path):
    mod = _load()
    root = _tree(tmp_path, {"a.tsx": "// fontSize: 48 was here\n  title: { fontSize: 36 },\n"})
    assert [s.px for s in mod.display_band(root)] == [36]


# ── the classifier's second pass ─────────────────────────────────────────────
#
# A one-line window sees the glyph only when the glyph is next to the size.
# Three sites in this tree put it somewhere else, and all three were counted as
# `type` — which is the expensive direction to be wrong in, because `type` is
# the side that argues for a new token.
#
#   * `alertIcon: { fontSize: 32 }` in a style object, used 160 lines away as
#     `<span style={s.alertIcon}>☢️</span>`
#   * `<span style={{ fontSize: 32 }}>{STATUS_ICON[status]}</span>`, where
#     STATUS_ICON is a table of ✅ ⚠️ ❌ ❓ at the top of the file
#
# So a site that survives the first pass gets a second one against the names it
# is reachable by: the style key it is defined under, and any SCREAMING_SNAKE
# table named in its JSX child.


def test_a_named_style_used_with_a_glyph_elsewhere_is_a_glyph(tmp_path):
    mod = _load()
    root = _tree(
        tmp_path,
        {
            "a.tsx": (
                "export const Alert = () => (\n"
                "  <span style={s.alertIcon}>☢️</span>\n"
                ");\n"
                "const s = {\n"
                "  alertIcon: {\n"
                "    fontSize: 32, flexShrink: 0,\n"
                "  },\n"
                "};\n"
            )
        },
    )
    assert [site.kind for site in mod.display_band(root)] == ["glyph"]


def test_a_named_style_used_with_text_stays_type(tmp_path):
    """The control. Without it the second pass could classify everything."""
    mod = _load()
    root = _tree(
        tmp_path,
        {
            "a.tsx": (
                "export const Title = () => <h1 style={s.title}>Risk</h1>;\n"
                "const s = {\n"
                "  title: {\n"
                "    fontSize: 36, fontWeight: 800,\n"
                "  },\n"
                "};\n"
            )
        },
    )
    assert [site.kind for site in mod.display_band(root)] == ["type"]


def test_a_glyph_table_named_in_the_child_is_a_glyph(tmp_path):
    mod = _load()
    root = _tree(
        tmp_path,
        {
            "a.tsx": (
                "const STATUS_ICON: Record<string, string> = {\n"
                "  healthy: '✅',\n"
                "  unhealthy: '❌',\n"
                "};\n"
                "const B = () => <span style={{ fontSize: 32 }}>{STATUS_ICON[status]}</span>;\n"
            )
        },
    )
    assert [site.kind for site in mod.display_band(root)] == ["glyph"]


def test_a_currency_symbol_is_type_not_a_glyph(tmp_path):
    """`₿`, `Ξ` and `₮` are text: they inherit `color`, they are set in the page's
    font, and `fontSize` is the correct and only way to size them. Calling them
    glyphs would push four real typographic sites out of the count that decides
    whether the scale needs extending."""
    mod = _load()
    root = _tree(
        tmp_path,
        {"a.tsx": "const M = { BTC: { icon: '₿' } };\n<span style={{ fontSize: 32 }}>{m.icon}</span>\n"},
    )
    assert [site.kind for site in mod.display_band(root)] == ["type"]
