# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""The emoji codemod may only write where an element is legal.

`scripts/frontend_emoji_codemod.py` replaces a glyph with a Lucide element, and
an element is not a string. So the rule that makes it safe is narrow and
mechanical: **convert only a glyph that sits outside every string literal in a
`.tsx` file.** A bare glyph in that position can only be JSX children — anywhere
else in TypeScript it would not parse.

The failures it is guarding against are asymmetric, which is why the rule is
drawn there rather than anywhere looser:

* Converting a glyph inside a string produces `'<Zap /> Plan'` — a literal
  eleven-character string rendered to the user. Silent, and shipped.
* Refusing to convert one costs nothing: it stays in the ratchet, counted.

Three shapes deliberately NOT converted, each present in this tree:

* a glyph in a `label:` or `title:` string in a data array — the component that
  renders it has to take an icon first, which is a design change;
* a regional-indicator flag — Lucide has no flags, and on Windows the pair
  already renders as letters, so the honest replacement is a country code;
* a glyph in a whole-line comment — prose wants rewording, not an element.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from frontend_emoji_codemod import ICONS, outside_strings, rewrite


def test_it_converts_a_glyph_in_jsx_children():
    out, counts, skipped = rewrite("      <div>⚡ Plan Trade</div>\n")
    assert '<Zap size="1em" aria-hidden /> Plan Trade' in out
    assert counts == {"Zap": 1}
    assert skipped == []


def test_it_refuses_a_glyph_inside_a_single_quoted_string():
    """`'<Zap /> Plan'` would be rendered to the user, verbatim and silently."""
    src = "      {ok ? '⚡ Plan' : 'off'}\n"
    out, counts, skipped = rewrite(src)
    assert out == src
    assert counts == {}
    assert skipped and skipped[0][1] == "inside a string"


def test_it_refuses_a_glyph_inside_a_template_literal():
    src = "      title={`${n} components — ✅ ok`}\n"
    assert rewrite(src)[0] == src


def test_it_refuses_a_glyph_inside_a_double_quoted_string():
    src = '      const label = "⚠ blackout";\n'
    assert rewrite(src)[0] == src


def test_it_refuses_a_glyph_in_a_whole_line_comment():
    """Prose wants rewording, not an element — an element in a comment is dead."""
    src = "  // the ⚠ here was removed on purpose\n"
    out, _, skipped = rewrite(src)
    assert out == src
    assert skipped and skipped[0][1] == "in a comment"


def test_it_reports_a_glyph_it_has_no_icon_for():
    """A flag has no Lucide equivalent. Reported, never guessed at."""
    src = "      <span>\U0001f1fa\U0001f1f8 US CPI</span>\n"
    out, _, skipped = rewrite(src)
    assert out == src
    assert skipped and skipped[0][1] == "no icon mapped"


def test_it_converts_every_glyph_on_a_line():
    out, counts, _ = rewrite("      <div>✅ {ok} / ❌ {err}</div>\n")
    assert '<CheckCircle2 size="1em" aria-hidden />' in out
    assert '<XCircle size="1em" aria-hidden />' in out
    assert counts == {"CheckCircle2": 1, "XCircle": 1}


def test_it_is_idempotent():
    once, _, _ = rewrite("      <div>⚡ Plan</div>\n")
    twice, counts, _ = rewrite(once)
    assert twice == once
    assert counts == {}


def test_outside_strings_tracks_quote_state():
    line = "  <div title='a ⚠ b'>⚠</div>"
    spans = outside_strings(line)
    inside = line.index("⚠")
    outside = line.rindex("⚠")
    assert not any(a <= inside < b for a, b in spans)
    assert any(a <= outside < b for a, b in spans)


def test_an_escaped_quote_does_not_end_the_string():
    """`'it\\'s ⚠'` stays one string; a naive scanner reopens it and converts."""
    src = "      {x ? 'it\\'s ⚠' : y}\n"
    assert rewrite(src)[0] == src


@pytest.mark.parametrize("glyph,icon", sorted(ICONS.items()))
def test_every_mapping_in_the_table_actually_applies(glyph: str, icon: str):
    out, counts, _ = rewrite(f"      <div>{glyph} x</div>\n")
    assert f'<{icon} size="1em" aria-hidden />' in out
    assert counts == {icon: 1}


def test_a_display_glyph_keeps_its_size_without_being_measured():
    """The reason the emission is `1em` and not a pixel count.

    `fontSize: 32` next to a pictograph is an empty-state illustration. An
    earlier version of this codemod refused those 94 sites rather than emit
    `size={13}` and shrink them by two thirds silently. `width="1em"` removes
    the question: the icon inherits the same font size the glyph did, so the
    surrounding style is not edited and no size is guessed — and, unlike a pixel
    number, it still follows `data-density`, which is the whole defect
    `frontend_size_ratchet.py` exists for.
    """
    out, counts, skipped = rewrite("      <div style={{ fontSize: 32, marginBottom: 12 }}>\U0001f4cb</div>\n")
    assert '<ClipboardList size="1em" aria-hidden />' in out
    assert "fontSize: 32" in out, "the style that sizes it must be left alone"
    assert counts == {"ClipboardList": 1}
    assert skipped == []


def test_a_token_font_size_sizes_the_icon_too():
    """`var(--fs-hero)` cannot be read as a number, and does not need to be."""
    out, _, _ = rewrite("      <span style={{ fontSize: 'var(--fs-hero)' }}>\u26a0</span>\n")
    assert '<AlertTriangle size="1em" aria-hidden />' in out
    assert "var(--fs-hero)" in out


def test_it_adds_only_names_a_file_does_not_already_import():
    """A file may carry more than one lucide import; the union is what counts.

    `Settings.tsx` has two — one for its own chrome, one for its tab table — and
    merging into the first without reading the second produced
    `Duplicate identifier 'Zap'`. Loud, caught by tsc, and caught here first.
    """
    from frontend_emoji_codemod import _ensure_import

    src = (
        "import { SlidersHorizontal } from 'lucide-react';\n"
        "import React from 'react';\n"
        "import { Banknote, Zap } from 'lucide-react';\n"
    )
    out = _ensure_import(src, {"Zap", "Banknote", "Check"})
    assert out.count("Zap") == 1
    assert out.count("Banknote") == 1
    assert "Check, SlidersHorizontal" in out


def test_it_adds_nothing_when_every_name_is_already_imported():
    from frontend_emoji_codemod import _ensure_import

    src = "import { Zap } from 'lucide-react';\n"
    assert _ensure_import(src, {"Zap"}) == src


def test_it_sees_a_name_that_is_already_imported_under_an_alias():
    """`Map as MapIcon` already provides `MapIcon`.

    Reading only the left-hand name re-imported it, and `tsc` answered
    "Duplicate identifier 'MapIcon'" twice on one line.
    """
    from frontend_emoji_codemod import _ensure_import

    src = "import { Map as MapIcon, Zap } from 'lucide-react';\n"
    assert _ensure_import(src, {"MapIcon"}) == src
    assert _ensure_import(src, {"Map"}) == src


#: Names lucide-react exports that would shadow a JS global or a component this
#: tree already imports. Mapping a glyph to one of these compiles until the file
#: happens to use the thing it shadowed, and then fails somewhere unrelated.
_SHADOWING = {
    "Map",  # the JS Map constructor — PlatformConfiguration has `new Map<string, string>()`
    "Set",
    "Link",  # react-router-dom's Link, imported by 40+ pages here
    "Image",
    "Text",
    "Table",
    "Menu",
    "Option",
    "Frame",
    "History",
    "Navigator",
    "Screen",
    "Range",
    "Selection",
}


def test_no_glyph_maps_to_a_name_that_shadows_something():
    """Found the hard way, twice in one run.

    `🗺 -> Map` put `import { Map }` above a `new Map<string, string>()` 1,100
    lines below, and the error surfaced as "'Map' cannot be used as a JSX
    component" in a different file. `🔗 -> Link` would have collided with
    react-router's `Link` in any page that navigates. lucide-react exports
    `MapIcon` and `Link2` for the same two icons, so the fix costs nothing.
    """
    clashes = sorted({icon for icon in ICONS.values()} & _SHADOWING)
    assert clashes == [], (
        f"{clashes} shadow a global or a common import — pick lucide's alternative name "
        "(MapIcon for Map, Link2 for Link)"
    )
