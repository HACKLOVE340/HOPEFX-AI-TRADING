#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate J: circular import detection in guarded packages.
#
# Circular imports in Python cause ``ImportError`` or subtle attribute
# ``AttributeError`` failures at runtime depending on import order.  In trading
# platform packages (core, risk, execution, kill_switch, brokers) a circular
# import can silently corrupt module-level singletons (e.g. the kill switch
# state) or prevent the application from starting entirely.
#
# This gate builds an intra-repo import graph via AST (no runtime import) and
# runs a DFS-based cycle detection over the GUARDED_PACKAGES.  It reports every
# distinct cycle found so they can all be fixed in one pass.
#
# Only intra-repo imports are included in the graph — stdlib and third-party
# imports are ignored (they can't form cycles with our code).
#
# Exits 0 on pass (no cycles), 1 on failure.
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

GUARDED_PACKAGES: tuple[str, ...] = (
    "core",
    "risk",
    "execution",
    "kill_switch",
    "brokers",
    "ml",
    "brain",
    "strategies",
    "data_layer",
    "auth",
    "api",
)

EXCLUDED_PATTERNS: tuple[str, ...] = (
    "test_",
    "conftest",
    ".venv/",
    "site-packages/",
    "frontend/",
    "dashboard/",
    "mobile",
    "docs/",
    "alembic/",
    "migrations/",
    "scripts/",
)

# Packages whose top-level names exist in stdlib or popular third-party libs.
# Used to avoid treating e.g. ``import logging`` as an intra-repo import.
_KNOWN_EXTERNAL_PREFIXES: frozenset[str] = frozenset(
    {
        # stdlib
        "abc", "ast", "asyncio", "base64", "binascii", "builtins", "cachetools",
        "calendar", "collections", "concurrent", "contextlib", "copy", "csv",
        "dataclasses", "datetime", "decimal", "enum", "email", "functools",
        "gc", "getpass", "glob", "hashlib", "hmac", "html", "http", "importlib",
        "inspect", "io", "itertools", "json", "logging", "math", "multiprocessing",
        "operator", "os", "pathlib", "pickle", "pprint", "queue", "random",
        "re", "secrets", "select", "signal", "socket", "ssl", "stat", "string",
        "struct", "subprocess", "sys", "tempfile", "threading", "time",
        "traceback", "typing", "typing_extensions", "types", "unicodedata",
        "unittest", "urllib", "uuid", "warnings", "weakref", "xml", "zlib",
        # common third-party
        "aiohttp", "aioredis", "alembic", "anthropic", "anyio", "arrow",
        "attr", "attrs", "backoff", "bcrypt", "boto3", "botocore", "celery", "certifi", "cffi", "charset_normalizer", "click", "cryptography",
        "dateutil", "dotenv", "exceptiongroup", "fastapi", "flower", "google",
        "gzip", "httpx", "httpcore", "idna", "jinja2", "jose", "jwt",
        "kombu", "loguru", "lxml", "mako", "markupsafe", "matplotlib",
        "motor", "msgpack", "numpy", "oandapyV20", "openai", "orjson",
        "packaging", "pandas", "passlib", "pgcrypto", "PIL", "prometheus_client",
        "psutil", "psycopg2", "psycopg", "pydantic", "pymongo", "pytest",
        "python_multipart", "pytz", "redis", "requests", "ruff", "scipy",
        "sentry_sdk", "setuptools", "six", "sklearn", "sniffio", "sqlalchemy",
        "starlette", "stripe", "structlog", "tenacity", "toml", "torch",
        "tqdm", "twilio", "tzdata", "ujson", "uvicorn", "uvloop", "vega",
        "websockets", "werkzeug", "wrapt", "yaml",
        # test libs
        "factory_boy", "faker", "freezegun", "hypothesis", "moto",
        "pytest_asyncio", "responses", "aioresponses", "fakeredis",
    }
)


def _is_external(module_root: str) -> bool:
    return module_root in _KNOWN_EXTERNAL_PREFIXES


def _py_files(root: Path, package: str) -> list[Path]:
    pkg_dir = root / package
    if not pkg_dir.exists():
        return []
    return [
        p
        for p in pkg_dir.rglob("*.py")
        if not any(exc in str(p) for exc in EXCLUDED_PATTERNS)
    ]


def _module_name(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    return str(rel).replace("/", ".").removesuffix(".py")


def _resolve_import(module: str, current_package: str, root: Path) -> str | None:
    """
    Return the canonical dotted module name if the import targets an intra-repo
    file, else None.
    """
    parts = module.split(".")
    root_pkg = parts[0]

    if _is_external(root_pkg):
        return None

    # Check if the module (or any prefix) maps to a file/package in the repo
    # Walk from most-specific to least-specific
    for length in range(len(parts), 0, -1):
        candidate = ".".join(parts[:length])
        candidate_path = root / Path(*candidate.split("."))
        if (candidate_path.with_suffix(".py")).exists():
            return candidate
        if (candidate_path / "__init__.py").exists():
            return candidate

    # Relative imports already have module resolved by ast (level > 0 gives
    # absolute name after resolution), fall through to check top-level package
    if root_pkg in {p for p in GUARDED_PACKAGES}:
        return module

    return None


def _build_graph(
    root: Path,
    packages: tuple[str, ...],
) -> dict[str, set[str]]:
    """Build adjacency list: module → set of intra-repo modules it imports.

    Only **module-level** imports are included.  Deferred imports inside
    function or class bodies are the standard Python pattern for breaking
    circular dependencies and are intentionally excluded from this graph.
    """
    graph: dict[str, set[str]] = {}

    all_files: list[Path] = []
    for pkg in packages:
        all_files.extend(_py_files(root, pkg))

    for py_file in all_files:
        mod = _module_name(py_file, root)
        if mod not in graph:
            graph[mod] = set()

        try:
            source = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        pkg_prefix = mod.rsplit(".", 1)[0] if "." in mod else mod

        # Only walk top-level statements — skip anything inside functions/classes
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    resolved = _resolve_import(alias.name, pkg_prefix, root)
                    if resolved and resolved != mod:
                        graph[mod].add(resolved)

            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                # Resolve relative imports to absolute
                if node.level and node.level > 0:
                    base_parts = mod.split(".")
                    up = node.level
                    if up > len(base_parts):
                        # Invalid relative import — goes beyond package root.
                        # This is a Python error at runtime; skip the edge to
                        # avoid masking real cycles with a bad resolution.
                        continue
                    base = ".".join(base_parts[:-up])
                    abs_module = f"{base}.{node.module}" if base else node.module
                else:
                    abs_module = node.module

                resolved = _resolve_import(abs_module, pkg_prefix, root)
                if resolved and resolved != mod:
                    graph[mod].add(resolved)

                # Also check imported names as possible submodules
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    full = f"{abs_module}.{alias.name}"
                    resolved2 = _resolve_import(full, pkg_prefix, root)
                    if resolved2 and resolved2 != mod:
                        graph[mod].add(resolved2)

    return graph


def _find_all_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """
    Return a list of cycles.  Each cycle is expressed as the minimal set of
    nodes that form it (Johnson's algorithm simplified to SCC detection via
    Tarjan's, then only SCC with size > 1 are returned as cycles).
    """
    # Tarjan's SCC
    index_counter = [0]
    stack: list[str] = []
    lowlinks: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: set[str] = set()
    sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        index[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in graph.get(v, set()):
            if w not in index:
                if w in graph:  # only follow intra-graph edges
                    strongconnect(w)
                    lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif w in on_stack:
                lowlinks[v] = min(lowlinks[v], index[w])

        if lowlinks[v] == index[v]:
            scc: list[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.append(w)
                if w == v:
                    break
            if len(scc) > 1:
                sccs.append(sorted(scc))

    for v in graph:
        if v not in index:
            strongconnect(v)

    return sccs


def main() -> int:
    graph = _build_graph(REPO_ROOT, GUARDED_PACKAGES)

    # Trim graph to only nodes reachable within guarded packages
    guarded_mods = {m for m in graph if m.split(".")[0] in set(GUARDED_PACKAGES)}
    trimmed: dict[str, set[str]] = {
        m: {dep for dep in deps if dep.split(".")[0] in set(GUARDED_PACKAGES)}
        for m, deps in graph.items()
        if m in guarded_mods
    }

    cycles = _find_all_cycles(trimmed)

    if cycles:
        print(f"Gate J FAILED — {len(cycles)} circular import group(s) detected:")
        for i, scc in enumerate(cycles, 1):
            print(f"\n  Cycle group {i} ({len(scc)} modules):")
            for mod in scc:
                # Show which modules in the SCC this one imports
                intra_imports = trimmed.get(mod, set()) & set(scc)
                targets = ", ".join(sorted(intra_imports)) if intra_imports else "(none)"
                print(f"    {mod}  →  {targets}")
        print()
        print("Fix: break the cycle by extracting shared types/interfaces into a")
        print("separate module that neither side imports from (e.g. core/domain_models.py).")
        return 1

    print(
        f"Gate J PASSED — no circular imports detected across "
        f"{len(trimmed)} modules in {', '.join(GUARDED_PACKAGES)}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
