# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The nan_leak rule must scan code, not documentation.

`security/code_analyzer.py` already computes `docstring_lines` and skips them for
the look-ahead rule, with the reason written in `_build_docstring_lines`:

    This prevents the regex scanner from flagging code examples in docstrings
    (e.g. shift(-1) in a docstring showing what NOT to do).

The nan_leak rule never consulted it. So a docstring that *describes* an
aggregation — "both engines used ``returns[returns < 0].std()``" — raised a
high-severity finding on a line that is not executed, in a repo whose own gate
requires zero findings. The exemption existed and the rule did not invoke it,
which is this audit's signature shape applied to the analyzer itself.

Second gap: `np.sqrt(252)` was flagged. The rule flags `np.log|sqrt|exp(`
because those produce NaN for invalid inputs — but not for a numeric literal,
where the result is decided at authoring time. The pre-existing Sortino line
passed only because an unrelated `np.nan_to_num(` elsewhere in the expression
satisfied the ±5-line guard window; remove it and the constant tripped the gate.

Neither change can hide a real leak: a string is not executed, and
`np.sqrt(<literal>)` cannot be NaN unless it was written that way.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def scan(tmp_path, monkeypatch):
    """Scan a sample file the analyzer will treat as production code.

    Two traps make a naive harness pass vacuously. The analyzer skips test files
    (`is_test = "/test" in rel`), and pytest's tmp_path is named after the test,
    so a sample written there is silently exempt — every "still a finding"
    assertion would pass against a scanner that never ran. `_rel` also falls
    back to the absolute path when the file is outside PROJECT_ROOT, which puts
    "/tmp/pytest-of-root/test_..." back into the string. Pointing PROJECT_ROOT at
    tmp_path gives a clean relative path that reads as production code.
    """
    from security import code_analyzer

    monkeypatch.setattr(code_analyzer, "PROJECT_ROOT", tmp_path)

    def _scan(source: str):
        pkg = tmp_path / "prod_sample_pkg"
        pkg.mkdir(exist_ok=True)
        path = pkg / "sample.py"
        path.write_text(source, encoding="utf-8")
        assert "/test" not in code_analyzer._rel(path), (
            f"the sample path still reads as a test file: {code_analyzer._rel(path)}"
        )
        return [i for i in code_analyzer.scan_file(path) if i.category == "nan_leak"]

    return _scan


def test_an_aggregation_described_in_a_docstring_is_not_a_finding(scan):
    source = '''
def downside_deviation(returns):
    """Root-mean-square shortfall.

    This replaces ``returns[returns < 0].std()``, which measured the dispersion
    among the losses rather than the shortfall below the target.
    """
    return 0.0
'''
    assert scan(source) == []


def test_a_single_line_docstring_is_not_a_finding(scan):
    source = '''
def f(df):
    """Was df[\'x\'].mean() — see F120."""
    return 0.0
'''
    assert scan(source) == []


def test_a_real_aggregation_is_still_a_finding(scan):
    """The rule must keep working. This is the case it exists for."""
    source = """
def f(df):
    return df['x'].mean()
"""
    found = scan(source)
    assert found, "the rule no longer flags an unguarded aggregation"


def test_a_guarded_aggregation_is_still_clean(scan):
    source = """
def f(df):
    df = df.dropna()
    return df['x'].mean()
"""
    assert scan(source) == []


def test_sqrt_of_a_numeric_literal_is_not_a_finding(scan):
    source = """
import numpy as np


def annualise(ratio):
    return float(np.sqrt(252) * ratio)
"""
    assert scan(source) == []


@pytest.mark.parametrize("literal", ["252", "252.0", "1e3", "0.5"])
def test_every_numeric_literal_form_is_exempt(scan, literal):
    source = f"""
import numpy as np


def f(x):
    return float(np.sqrt({literal}) * x)
"""
    assert scan(source) == []


def test_sqrt_of_a_variable_is_still_a_finding(scan):
    """A variable can hold a negative number, which is what the rule is for."""
    source = """
import numpy as np


def f(variance):
    return float(np.sqrt(variance))
"""
    assert scan(source), "np.sqrt of a variable must still be flagged"


def test_a_literal_call_does_not_mask_a_real_one_on_the_same_line(scan):
    source = """
import numpy as np


def f(variance):
    return float(np.sqrt(252) * np.sqrt(variance))
"""
    assert scan(source), "the literal exemption swallowed a genuine finding beside it"


def test_an_aggregation_described_in_a_comment_is_not_a_finding(scan):
    """`in_doc` covers triple-quoted strings only. A `#` comment is not executed
    either, and the rule flagged one — the comment block explaining this fix in
    `security/code_analyzer.py` tripped its own rule, which is how the gap was
    found."""
    source = """
def f(x):
    # this replaces df['x'].mean(), which propagated NaN
    return x
"""
    assert scan(source) == []


def test_a_hash_inside_a_string_does_not_hide_code(scan):
    """The comment marker is located with `_strip_string_literals`, so a `#`
    inside a string literal must not truncate the line before a real finding."""
    source = """
def f(df):
    label = "# not a comment"
    return label, df['x'].mean()
"""
    assert scan(source), "a '#' inside a string was treated as the start of a comment"


def test_a_real_finding_before_a_comment_still_fires(scan):
    source = """
def f(df):
    return df['x'].mean()  # no guard anywhere
"""
    assert scan(source)
