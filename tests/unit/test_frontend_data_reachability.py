# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""A page's data is reached through the tree it renders, not through its file.

`docs/audit/FRONTEND_HANDOVER.md` carried a list of "eleven routed pages that
call no API at all", of which five were named as worth wiring. Re-measured,
**all five were already wired** — through a child component, a lazy import, or
the global store. The list had been produced by looking for a fetch in the page
file, and a page that delegates looks exactly like a page with nothing behind
it.

Every test below drives a real throwaway tree rather than asserting from
reading the source, because the failure mode of this kind of script is not a
crash: it is a confident wrong answer, and each wrong answer this script has
already given is pinned here as its own test.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "frontend_data_reachability.py"


def _load(root: Path):
    """Import the module with its scan root pointed at a throwaway tree."""
    spec = importlib.util.spec_from_file_location("data_reachability", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.REPO = root
    return mod


def _tree(tmp_path: Path, files: dict[str, str], routes: str = "") -> Path:
    """Build `<root>/frontend/src/...` and return the root."""
    src = tmp_path / "frontend" / "src"
    for rel, body in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (src / "App.tsx").write_text(routes, encoding="utf-8")
    return tmp_path


ROUTER = (
    "const Page = React.lazy(() => import('./pages/Page'));\n"
    '<Routes><Route path="/*" element={<AppShell />} /></Routes>\n'
)

FETCHES = "export const Child = () => { tradingApi.positions(); return null; };\n"
INERT = "export const Child = () => null;\n"


# ── the defect this script exists to stop ────────────────────────────────────


def test_a_page_that_delegates_to_a_child_is_wired(tmp_path):
    """The exact shape the handover's list got wrong: AIAssistant/<AIChat>."""
    root = _tree(
        tmp_path,
        {
            "pages/Page.tsx": "import { Child } from '../components/Child';\nexport default () => <Child />;\n",
            "components/Child.tsx": FETCHES,
        },
        ROUTER,
    )
    result = _load(root).measure()
    assert result["static"] == []
    entry = result["wired"]["frontend/src/pages/Page.tsx"]
    assert entry["own"] == "false"
    assert entry["in"] == "frontend/src/components/Child.tsx"


def test_a_page_that_lazy_loads_its_section_is_wired(tmp_path):
    """SystemReliability's shape — `lazy(() => import('./superadmin/...'))`."""
    root = _tree(
        tmp_path,
        {
            "pages/Page.tsx": "const S = lazy(() => import('./sections/Panel'));\nexport default () => <S />;\n",
            "pages/sections/Panel.tsx": FETCHES,
        },
        ROUTER,
    )
    assert _load(root).measure()["static"] == []


def test_a_page_that_only_reads_the_store_is_wired(tmp_path):
    """PositionDetail's shape. The data is live; this page did not fetch it."""
    root = _tree(
        tmp_path,
        {"pages/Page.tsx": "const p = useStore(selectPositions);\nexport default () => null;\n"},
        ROUTER,
    )
    result = _load(root).measure()
    assert result["static"] == []
    assert result["wired"]["frontend/src/pages/Page.tsx"]["via"] == "store"


def test_a_page_with_nothing_behind_it_is_reported(tmp_path):
    """The floor. If this ever passes vacuously the script says "all wired"
    for a tree it never read, which is indistinguishable from success."""
    root = _tree(
        tmp_path,
        {
            "pages/Page.tsx": "import { Child } from '../components/Child';\nexport default () => <Child />;\n",
            "components/Child.tsx": INERT,
        },
        ROUTER,
    )
    result = _load(root).measure()
    assert result["static"] == ["frontend/src/pages/Page.tsx"]
    assert result["wired"] == {}


def test_it_reads_something_at_all(tmp_path):
    """A router that mounts nothing must not report 73 healthy pages."""
    root = _tree(tmp_path, {"pages/Page.tsx": FETCHES}, "")
    assert _load(root).measure()["routed"] == 0


# ── the wrong answers this script actually gave, each pinned ─────────────────


def test_a_generic_type_argument_does_not_hide_a_call(tmp_path):
    """First run reported TwoFactorSetup — five `api.get<T>(...)` calls, the
    page that enrols a second factor — as having no data behind it."""
    root = _tree(
        tmp_path,
        {"pages/Page.tsx": "api.get<StatusData>('/2fa/status');\nexport default () => null;\n"},
        ROUTER,
    )
    assert _load(root).measure()["static"] == []


def test_importing_the_data_layer_is_not_calling_it(tmp_path):
    """First run reported DocsPage — whose only state is a search box — as
    reaching live data, because everything reaches hooks/useApi.ts through
    PageShell. Importing the module that DEFINES `tradingApi` proves nothing."""
    root = _tree(
        tmp_path,
        {
            "pages/Page.tsx": "import { api } from '../hooks/useApi';\nexport default () => null;\n",
            "hooks/useApi.ts": "export const tradingApi = { positions: () => api.get('/p') };\n",
        },
        ROUTER,
    )
    assert _load(root).measure()["static"] == ["frontend/src/pages/Page.tsx"]


def test_a_call_written_in_a_comment_is_not_a_call(tmp_path):
    """F255, the fifth time. A checker that reads prose is not reading code."""
    root = _tree(
        tmp_path,
        {"pages/Page.tsx": "// TODO: call fetch('/api/x') here one day\nexport default () => null;\n"},
        ROUTER,
    )
    assert _load(root).measure()["static"] == ["frontend/src/pages/Page.tsx"]


def test_a_call_written_in_a_string_is_not_a_call(tmp_path):
    root = _tree(
        tmp_path,
        {"pages/Page.tsx": "const hint = \"use fetch('/api/x')\";\nexport default () => null;\n"},
        ROUTER,
    )
    assert _load(root).measure()["static"] == ["frontend/src/pages/Page.tsx"]


def test_a_call_inside_a_template_interpolation_is_a_call(tmp_path):
    """The other half: `${...}` inside a backtick string is code."""
    root = _tree(
        tmp_path,
        {"pages/Page.tsx": "const s = `x${tradingApi.positions()}y`;\nexport default () => null;\n"},
        ROUTER,
    )
    assert _load(root).measure()["static"] == []


def test_a_commented_out_import_is_not_followed(tmp_path):
    root = _tree(
        tmp_path,
        {
            "pages/Page.tsx": "// import { Child } from '../components/Child';\nexport default () => null;\n",
            "components/Child.tsx": FETCHES,
        },
        ROUTER,
    )
    assert _load(root).measure()["static"] == ["frontend/src/pages/Page.tsx"]


def test_a_double_slash_inside_a_string_does_not_start_a_comment(tmp_path):
    """A URL in a string used to swallow the rest of the line — and with it
    any call written after it."""
    root = _tree(
        tmp_path,
        {"pages/Page.tsx": "const u = 'https://x.example'; tradingApi.positions();\nexport default () => null;\n"},
        ROUTER,
    )
    assert _load(root).measure()["static"] == []


# ── the helpers, directly ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "// fetch(1)\n",
        "/* fetch(1) */\n",
        "/**\n * fetch(1)\n */\n",
    ],
)
def test_no_comments_blanks_every_comment_shape(text):
    mod = _load(REPO)
    assert "fetch" not in mod._no_comments(text)
    assert len(mod._no_comments(text)) == len(text)


def test_no_strings_keeps_the_import_specifier_for_the_walk():
    """`_no_comments` must NOT blank strings: the import walk reads them."""
    mod = _load(REPO)
    line = "import X from './components/Child';\n"
    assert "./components/Child" in mod._no_comments(line)
    assert mod._imports(mod._no_comments(line)) == ["./components/Child"]


def test_the_real_tree_is_measured_and_is_mostly_wired():
    """Against the repository itself, not a fixture — the numbers a successor
    reads in FRONTEND_HANDOVER.md come from here."""
    mod = _load(REPO)
    result = mod.measure()
    assert result["routed"] > 50, "route discovery stopped finding pages"
    # Every page reported static must be one a human has confirmed is static
    # BY DESIGN. Adding a page here is a decision, not a fix for a red test.
    assert set(result["static"]) == {
        "frontend/src/pages/DocsPage.tsx",
        "frontend/src/pages/PrivacyPolicy.tsx",
        "frontend/src/pages/TermsAndRiskDisclosure.tsx",
    }
