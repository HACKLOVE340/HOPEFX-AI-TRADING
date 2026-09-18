"""Task 7's done-condition: one door for every model call.

The gateway carries the budget ceiling, the fall-through chain, the guardrails
and the only audit record of what a model was asked and what it cost. All of
that is worth exactly nothing if a caller can reach a vendor around it -- and
two callers could: `api/brain.py` posted to api.anthropic.com, called the
`openai` SDK, and posted to Ollama's `/api/generate` inline, and
`brain/llm_agent.py` did the same. A control that is real and bypassed is this
audit's signature defect.

This test reads the source rather than mocking a call, because the property is
about what the repository permits, not about what one code path happened to do
on one run.

**Out of scope, deliberately:** `api/voice.py` posts to OpenAI's *audio*
endpoints (text-to-speech and transcription). Those are a different API surface
with a different request shape, and the gateway's `Provider.complete` does not
model them -- routing them through it would mean pretending an audio file is a
completion. They are named here so the omission is a decision on the record
rather than a gap nobody noticed.
"""

from __future__ import annotations

import ast
import pathlib

#: The only package allowed to talk to a model vendor.
_GATEWAY = "ai/gateway"

#: Audio, not completion. See the module docstring.
_AUDIO_ONLY = {"api/voice.py"}

#: Chat-completion endpoints. A module naming one of these is calling a model.
#:
#: Vendor HOSTS only. An earlier version of this list also matched the bare
#: paths "/api/chat" and "/api/generate" -- which are Ollama's, and also this
#: platform's own chat route, so it reported api/chat.py, api/community_chat.py
#: and core/startup_factories.py as vendor callers. Ollama is caught by the
#: base-URL check below instead, which is the only way to reach it.
_COMPLETION_URLS = (
    "api.anthropic.com/v1/messages",
    "api.openai.com/v1/chat/completions",
    "api.openai.com/v1/completions",
    "generativelanguage.googleapis.com",
)

#: Local inference is reached through this variable and nothing else. A module
#: reading it outside the gateway is calling a model directly.
_LOCAL_BASE_URL = "OLLAMA_BASE_URL"

#: What a module needs in order to actually issue the request.
_HTTP_CLIENTS = {"httpx", "requests", "aiohttp", "urllib3", "urllib.request"}

#: Vendor SDKs. Importing one is how a caller reaches a model without a URL.
_VENDOR_SDKS = {"openai", "anthropic", "google.generativeai", "ollama", "cohere", "mistralai"}


def _python_files() -> list[pathlib.Path]:
    root = pathlib.Path()
    skip = ("tests/", ".venv/", "node_modules/", "scripts/", "frontend/")
    return [path for path in root.rglob("*.py") if not any(str(path).startswith(prefix) for prefix in skip)]


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """The string Constant nodes that are docstrings, by identity."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", None) or []
        first = body[0] if body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            found.add(id(first.value))
    return found


def _string_constants(tree: ast.AST) -> list[str]:
    """String literals that are code, not prose.

    Two exclusions, both learned the hard way. Reading the file as text would
    count a docstring as a call site -- and `security/llm_wrapper.py` documents
    the two endpoints it USED to post to, in the docstring explaining that it no
    longer does, so scanning prose reports the fix as the defect (F255).
    Docstrings are therefore skipped by identity, not by pattern.
    """
    skip = _docstring_nodes(tree)
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
    ]


def test_no_module_outside_the_gateway_imports_a_vendor_sdk() -> None:
    offenders: list[str] = []
    for path in _python_files():
        rel = str(path)
        if rel.startswith(_GATEWAY) or rel in _AUDIO_ONLY:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for imported in _imports(tree):
            root = imported.split(".")[0]
            if imported in _VENDOR_SDKS or root in _VENDOR_SDKS:
                offenders.append(f"{rel} imports {imported}")
    assert not offenders, (
        "these modules reach a model vendor without the gateway's budget ceiling, "
        f"fall-through chain, guardrails or audit record: {offenders}"
    )


def test_no_module_outside_the_gateway_names_a_completion_endpoint() -> None:
    offenders: list[str] = []
    for path in _python_files():
        rel = str(path)
        if rel.startswith(_GATEWAY) or rel in _AUDIO_ONLY:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for literal in _string_constants(tree):
            for url in _COMPLETION_URLS:
                if url in literal:
                    offenders.append(f"{rel} names {url}")
    assert not offenders, (
        f"these modules call a model endpoint directly instead of through ai/gateway: {sorted(set(offenders))}"
    )


def test_no_module_outside_the_gateway_reaches_local_inference() -> None:
    """Local inference is a model call too, and carries the same controls."""
    offenders: list[str] = []
    for path in _python_files():
        rel = str(path)
        if rel.startswith(_GATEWAY) or rel in _AUDIO_ONLY:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        names_it = any(_LOCAL_BASE_URL in literal for literal in _string_constants(tree))
        # Naming the variable is not calling the model. `config/startup_validator.py`
        # checks that it is SET, which is the opposite of bypassing the gateway --
        # so a module only counts as a caller when it can also make the request.
        can_call = bool(_imports(tree) & _HTTP_CLIENTS)
        if names_it and can_call:
            offenders.append(rel)
    assert not offenders, f"these modules call local inference directly instead of through ai/gateway: {offenders}"


def test_the_gateway_itself_is_where_the_vendors_live() -> None:
    """The complement: this test is worthless if the adapters moved and it passed."""
    adapters = pathlib.Path("ai/gateway/adapters.py").read_text(encoding="utf-8")
    for url in ("api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com", _LOCAL_BASE_URL):
        assert url in adapters, f"{url} is not in the gateway's adapters; the boundary test is checking nothing"
