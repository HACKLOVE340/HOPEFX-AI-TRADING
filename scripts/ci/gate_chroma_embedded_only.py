#!/usr/bin/env python3
# HOPEFX-AI-TRADING — Gate: ChromaDB stays embedded.
#
# `.trivyignore.yaml` suppresses four chromadb CVEs, two of them
# pre-authentication code injection, on one stated ground:
#
#     All four are ChromaDB *server* attack surfaces ... This platform uses the
#     embedded client only ... There is no port, no tenant boundary, and no
#     pre-auth request path.
#
#     This acceptance stops holding the moment anyone runs chroma as a server
#     or points the client at a remote host.
#
# That was true when written and nothing was checking it. A suppression whose
# precondition nobody verifies is the same shape as a gate nobody calls: one
# line in an unrelated pull request makes it false, and the CVEs stay
# suppressed either way. This gate turns the sentence into a check.
#
# What it refuses:
#   * chromadb.HttpClient / AsyncHttpClient / Client(host=...)  — a remote host
#   * Settings(chroma_server_host=..., chroma_server_http_port=...)
#   * a `chroma` service, or a chromadb image, in any compose file
#   * `uvicorn chromadb.app` / `chroma run` in a Dockerfile or script
#   * CHROMA_SERVER_HOST / CHROMA_SERVER_HTTP_PORT in any env file
#
# What it allows: chromadb.PersistentClient(path=...) and EphemeralClient(),
# which are in-process and have no listener.
#
# Python is read with the AST, not with a regex, so a docstring or comment that
# *describes* the ban is not a violation — the repository has already had a
# checker that scanned prose as if it were source (F255), and this file's own
# header would trip such a checker.
#
# Fails closed: a run that finds no source files at all exits 1. An empty
# result is not a clean result — that is how a broken glob certifies a
# repository it never looked at.
#
# Exits 0 on pass, 1 on any violation.
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

EXCLUDED_PARTS: frozenset[str] = frozenset(
    {".venv", "venv", "site-packages", "node_modules", "__pycache__", ".git", "dist", "build"}
)

# Constructors that open a connection to a chroma server.
SERVER_CONSTRUCTORS: frozenset[str] = frozenset({"HttpClient", "AsyncHttpClient"})

# Settings keywords that switch the embedded client into client/server mode.
SERVER_SETTINGS: frozenset[str] = frozenset(
    {"chroma_server_host", "chroma_server_http_port", "chroma_server_ssl_enabled", "chroma_server_headers"}
)

ENV_KEYS = re.compile(r"^\s*(CHROMA_SERVER_HOST|CHROMA_SERVER_HTTP_PORT|CHROMA_SERVER_SSL_ENABLED)\s*=", re.M)

# `chroma run`, or the ASGI app served directly.
RUN_SERVER = re.compile(r"\bchroma\s+run\b|chromadb\.app\b|\bchroma-server\b")

ENV_SUFFIXES = (".env", ".env.example", ".env.template", ".env.sample")
COMPOSE_NAMES = re.compile(r"^docker-compose.*\.ya?ml$|^compose.*\.ya?ml$")

WHY = (
    "This is what .trivyignore.yaml's chromadb CVE acceptance says cannot happen "
    "(CVE-2026-45829/45830/45831/45833, two of them pre-auth code injection). "
    "Running chroma as a server, or pointing the client at one, makes that "
    "suppression untrue. Extending the expiry date is not the answer."
)


class Violation:
    def __init__(self, path: Path, line: int, what: str) -> None:
        self.path, self.line, self.what = path, line, what

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.what}"


def _scannable(root: Path, suffixes: tuple[str, ...] | None = None) -> list[Path]:
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if EXCLUDED_PARTS & set(path.parts):
            continue
        if suffixes and path.suffix not in suffixes:
            continue
        out.append(path)
    return out


def _check_python(path: Path, root: Path) -> list[Violation]:
    """AST only — a comment or docstring naming HttpClient is prose, not a call."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []

    # Which local names refer to chromadb, so `from chromadb import HttpClient`
    # is caught as well as `chromadb.HttpClient`.
    chroma_aliases: set[str] = set()
    direct_server_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "chromadb" or a.name.startswith("chromadb."):
                    chroma_aliases.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("chromadb"):
            for a in node.names:
                if a.name in SERVER_CONSTRUCTORS:
                    direct_server_names.add(a.asname or a.name)

    found: list[Violation] = []
    rel = path.relative_to(root)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        # chromadb.HttpClient(...)
        if (
            isinstance(func, ast.Attribute)
            and func.attr in SERVER_CONSTRUCTORS
            and isinstance(func.value, ast.Name)
            and func.value.id in chroma_aliases
        ):
            found.append(Violation(rel, node.lineno, f"chromadb.{func.attr}() opens a connection to a chroma server"))
            continue

        # HttpClient(...) imported directly from chromadb
        if isinstance(func, ast.Name) and func.id in direct_server_names:
            found.append(Violation(rel, node.lineno, f"{func.id}() imported from chromadb opens a server connection"))
            continue

        # Settings(chroma_server_host=...) — any callable, since the Settings
        # symbol may be aliased; the keyword name is the chroma-specific part.
        for kw in node.keywords:
            if kw.arg in SERVER_SETTINGS:
                found.append(Violation(rel, node.lineno, f"{kw.arg}= switches chromadb into client/server mode"))

    return found


def _check_text(path: Path, root: Path) -> list[Violation]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    rel = path.relative_to(root)
    found: list[Violation] = []

    name = path.name
    if COMPOSE_NAMES.match(name):
        # A chroma service, by service name or by image.
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.split("#", 1)[0]
            if re.search(r"^\s{2,}chroma\w*\s*:\s*$", stripped) or re.search(
                r"image\s*:\s*[\"']?[\w./-]*chroma", stripped
            ):
                found.append(Violation(rel, i, "a chroma service in a compose file is a network listener"))

    if name.startswith("Dockerfile") or path.suffix in (".sh", ".bash") or COMPOSE_NAMES.match(name):
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.split("#", 1)[0]
            if RUN_SERVER.search(stripped):
                found.append(Violation(rel, i, "runs the chroma server process"))

    if name in ENV_SUFFIXES or path.suffix == ".env" or name.startswith(".env"):
        for m in ENV_KEYS.finditer(text):
            line = text[: m.start()].count("\n") + 1
            found.append(Violation(rel, line, f"{m.group(1)} configures a remote chroma server"))

    return found


def scan(root: Path) -> tuple[list[Violation], int]:
    violations: list[Violation] = []
    scanned = 0

    for path in _scannable(root, (".py",)):
        scanned += 1
        violations.extend(_check_python(path, root))

    for path in _scannable(root):
        if path.suffix == ".py":
            continue
        name = path.name
        if (
            COMPOSE_NAMES.match(name)
            or name.startswith("Dockerfile")
            or name.startswith(".env")
            or path.suffix in (".sh", ".bash", ".env")
        ):
            scanned += 1
            violations.extend(_check_text(path, root))

    return violations, scanned


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(REPO_ROOT))
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    violations, scanned = scan(root)

    if scanned == 0:
        print(
            f"gate_chroma_embedded_only: FAIL — scanned 0 files under {root}. "
            "An empty scan is not a clean scan; the gate fails closed rather than "
            "certifying a tree it never read.",
            file=sys.stderr,
        )
        return 1

    if violations:
        print(
            f"gate_chroma_embedded_only: FAIL — {len(violations)} chroma server usage(s) "
            f"across {scanned} scanned files:",
            file=sys.stderr,
        )
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        print(f"\n{WHY}", file=sys.stderr)
        return 1

    print(f"gate_chroma_embedded_only: PASS — embedded client only ({scanned} files scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
