"""The size codemod may only write where `var()` is resolved by the cascade.

`scripts/frontend_size_codemod.py` replaces an inline `fontSize: 13` with
`fontSize: 'var(--fs-body)'` so that the density tiers can reach it. The
substitution is byte-identical at the default density, so nothing moves — but
only where the value lands in CSS.

Two ways it could be wrong, and only one of them is loud:

* An **unquoted** `var(--fs-body)` is a TypeScript syntax error. Loud, caught
  by `tsc`, cannot ship.
* A **string handed to a chart** is silent. `lightweight-charts` takes
  `layout: { fontSize: 12 }` as a number and would be given something it cannot
  parse, in a file nobody opens until a chart looks wrong in production.

So this file is mostly about the silent one. Every case below is a shape that
actually occurs in `frontend/src`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from frontend_size_codemod import EXACT, rewrite, selftest


def test_the_mapping_is_still_byte_identical_to_the_token_scale():
    """A retuned token must leave the table, not silently move 763 call sites."""
    assert selftest() == 0


def test_it_rewrites_an_inline_style_attribute():
    src = "<p style={{ fontSize: 13, color: 'red' }}>x</p>"
    out, counts = rewrite(src, allow_declarations=True)
    assert "fontSize: 'var(--fs-body)'" in out
    assert counts == {"--fs-body": 1}


def test_it_quotes_the_replacement():
    """React appends `px` to a number and passes a string through untouched.

    An unquoted `var(--fs-body)` would not compile, which is the loud failure;
    this asserts the quoting rather than trusting tsc to catch it later, because
    a codemod that needs a type-check to be safe is a codemod that will be run
    with `--apply` by someone who then skips the type-check.
    """
    out, _ = rewrite("<p style={{ fontSize: 15 }}>x</p>", allow_declarations=True)
    assert "fontSize: 'var(--fs-value)'" in out
    assert "fontSize: var(" not in out


def test_it_leaves_a_size_that_sits_between_tokens_alone():
    """12 could be --fs-body (13) or --fs-label (11.5); either changes the page."""
    src = "<p style={{ fontSize: 12 }}>x</p>"
    out, counts = rewrite(src, allow_declarations=True)
    assert out == src
    assert counts == {}


def test_it_leaves_a_computed_size_alone():
    """A token cannot participate in arithmetic."""
    src = "<p style={{ fontSize: size * 0.115 }}>x</p>"
    assert rewrite(src, allow_declarations=True)[0] == src


def test_it_does_not_touch_a_size_outside_any_style_context():
    """A chart's own option object is not CSS, wherever it sits."""
    src = "createChart(el, { layout: { fontSize: 13 } });"
    out, counts = rewrite(src, allow_declarations=True)
    assert out == src
    assert counts == {}


def test_a_chart_file_gets_no_declaration_rewrites():
    """Rule 2 is withdrawn from any file that touches a canvas.

    The caller computes `allow_declarations` from the source — `_reads_canvas`
    — so this asserts the rewriter honours the flag rather than that the flag is
    computed correctly, which the next test covers.
    """
    src = "const axis = {\n  fontSize: 13,\n};\n"
    assert rewrite(src, allow_declarations=False)[0] == src
    assert "var(--fs-body)" in rewrite(src, allow_declarations=True)[0]


def test_the_canvas_exclusion_is_computed_from_the_source():
    from frontend_size_codemod import _reads_canvas

    assert _reads_canvas("import { createChart } from 'lightweight-charts';")
    assert _reads_canvas("const ctx = el.getContext('2d');")
    assert _reads_canvas("ctx.fillStyle = hue;")
    assert not _reads_canvas("import React from 'react';")


def test_it_does_not_touch_a_numeric_prop():
    """`fontSize={13}` is a component prop, not a style key."""
    src = "<Icon fontSize={13} />"
    assert rewrite(src, allow_declarations=True)[0] == src


def test_it_does_not_touch_a_longer_number_that_starts_with_a_token_value():
    """`fontSize: 130` must not become `var(--fs-body)0`.

    What protects this is the TABLE, not the pattern: "130" is captured whole
    and is not a key. Recorded because the obvious reading is that the pattern's
    trailing lookahead does the work, and it does not — this test passed against
    a deliberately unanchored regex, which is what sent me looking for the case
    the lookahead actually guards. That is the test below.
    """
    src = "<p style={{ fontSize: 130 }}>x</p>"
    assert rewrite(src, allow_declarations=True)[0] == src


def test_it_does_not_touch_a_size_that_opens_an_expression():
    """`fontSize: 13 + offset` must stay arithmetic.

    This is what the pattern's trailing `(?=[,}\n])` is for, and it is the one
    case an unanchored version gets wrong: it would capture the `13`, find it in
    the table, and emit `fontSize: 'var(--fs-body)' + offset` — a string
    concatenation that type-checks, renders "var(--fs-body)4", and is silent.

    Found by injection. Three injections were run against this file and this one
    survived all nineteen tests, which meant the anchor was a line of code no
    test held.
    """
    for src in (
        "<p style={{ fontSize: 13 + offset }}>x</p>",
        "<p style={{ fontSize: 13 * scale }}>x</p>",
        "<p style={{ fontSize: 15 - 1 }}>x</p>",
    ):
        assert rewrite(src, allow_declarations=True)[0] == src


def test_it_is_idempotent():
    src = "<p style={{ fontSize: 13 }}>x</p>"
    once, _ = rewrite(src, allow_declarations=True)
    twice, counts = rewrite(once, allow_declarations=True)
    assert twice == once
    assert counts == {}


def test_it_rewrites_every_size_in_a_multi_key_object():
    src = "<div style={{ fontSize: 21, padding: 13, gap: 15 }} />"
    out, counts = rewrite(src, allow_declarations=True)
    assert "fontSize: 'var(--fs-head)'" in out
    # padding and gap are NOT font sizes and are deliberately out of scope:
    # 13px of padding might be a card, a row, a modal or a button, and one token
    # would retune all four together.
    assert "padding: 13" in out
    assert "gap: 15" in out
    assert counts == {"--fs-head": 1}


@pytest.mark.parametrize("number,token", sorted(EXACT.items()))
def test_every_mapping_in_the_table_actually_applies(number: str, token: str):
    out, counts = rewrite(f"<p style={{{{ fontSize: {number} }}}}>x</p>", allow_declarations=True)
    assert f"fontSize: 'var({token})'" in out
    assert counts == {token: 1}
