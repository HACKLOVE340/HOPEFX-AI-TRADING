# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Documentation freshness — Group 3 Chapter 15.

Documentation rots silently. Unlike code, nothing fails when a document becomes
wrong; it simply misleads, and the cost lands on whoever trusted it.

## A correction to this module's own specification

Group 3 Chapter 15 asserted that a referential check "would have caught the
Python 3.10 error, the prop_firm_mode.json error, and every stale path
reference". That was written without testing it, and it is **wrong**. Tested
against all three historical errors:

| Error | What it said | Referential elements | Caught? |
|---|---|---|---|
| Python version | "Python 3.10 ... is what `Dockerfile` runs" | `Dockerfile` — exists | **No.** The false part is a version, not a path |
| Gitignore status | "`prop_firm_mode.json` is gitignored" | the file — exists | **No.** The false part is a status |
| Package purpose | "`data/` is legacy data files" | `data/` — exists | **No.** Purely semantic |

A pure referential check would have caught **none of them**. Every referenced
path in all three sentences existed; the false part was never the reference.

So this module has two layers rather than one, and the chapter has been corrected:

* **Referential** — paths and links. Genuinely valuable in a 198-document corpus
  where files move, but it catches drift rather than the three errors above.
* **Claims** — a small, explicit set of assertions that are machine-checkable and
  have already been wrong here. Gitignore status and pinned interpreter version
  are both in that set precisely because both have already misled somebody.

The third error remains out of reach of both, and the chapter now says so instead
of implying coverage this module does not have.

## Precision over recall, deliberately

A checker that reports three hundred findings on its first run is a checker that
gets disabled, which is `hopefx-dead-controls` again. The path rule is therefore
narrow: **a path is only reported when its parent directory exists.** A reference
to `foo/bar.py` where `foo/` does not exist is almost always an illustration; a
reference to `ai/gateway/gone.py` where `ai/gateway/` does exist is almost always
a file that moved.

That trade is stated rather than hidden: this check has low recall by design, and
it does not pretend to be a complete freshness audit.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

REPO = Path(__file__).resolve().parent.parent
BASELINE_PATH = REPO / "docs" / "FRESHNESS_BASELINE.toml"

#: Inline code spans and markdown links are where documents make references.
_CODE_SPAN = re.compile(r"`([^`\n]{2,120})`")
_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s#]+)(?:#[^)]*)?\)")

#: Things that look like paths but are illustrations, not claims.
_PLACEHOLDER = re.compile(
    r"(<[^>]+>|\.\.\.|\byour[-_]|\bexample\b|\bfoo\b|\bbar\b|path/to|\$\{|\{\{|%s|\*)",
    re.IGNORECASE,
)

#: A code span is a path candidate only if it looks like one.
_PATH_LIKE = re.compile(r"^[\w./-]+$")
_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".json", ".toml", ".yml", ".yaml", ".sh", ".cfg", ".ini", ".txt"}
)

#: "X is gitignored" / "X is not gitignored" / "X is tracked".
_GITIGNORE_CLAIM = re.compile(
    r"`([\w./-]+)`\s+(?:is|are)\s+(?P<neg>not\s+)?(?P<word>gitignored|git-ignored|ignored|tracked)",
    re.IGNORECASE,
)

#: "Python 3.10" stated as the target, near a Dockerfile or production mention.
_PY_VERSION_CLAIM = re.compile(r"\bPython\s+(\d+\.\d+)\b")
_PY_CONTEXT = re.compile(r"(production target|Dockerfile|docker image|what .{0,20}runs)", re.IGNORECASE)

#: A document REPORTING an old error is not making the claim.
#:
#: The first version of this check fired on two documents that both describe the
#: historical Python 3.10 mistake — a backlog table quoting the old wording, and
#: the Group 3 chapter that cites it as an example. Neither asserts anything.
#:
#: This is the same shape as a guard test that banned the very strings its own
#: docstrings contained: a checker that cannot distinguish *asserting* from
#: *quoting* fires hardest on the documents written to record the problem.
_REPORTING = re.compile(
    r"\b(stated|states that|said|claimed|claims that|previously|used to|incorrectly|"
    r"wrongly|formerly|historical|was already|old version|out of date|this previously)\b",
    re.IGNORECASE,
)


@dataclass
class Finding:
    rule: str
    document: str
    line: int
    detail: str
    blocking: bool = True

    def key(self) -> str:
        """Identity for baselining. Excludes the line number, which moves."""
        return f"{self.rule}|{self.document}|{self.detail}"


@dataclass
class Baseline:
    adopted: str = ""
    known: list[str] = field(default_factory=list)


def _strip_fenced_blocks(text: str) -> list[tuple[int, str]]:
    """Lines outside fenced code blocks, as (1-based line number, text).

    Fenced blocks hold shell transcripts and illustrative snippets whose paths are
    examples rather than claims. Checking them is where a documentation linter
    earns its reputation for noise.
    """
    out: list[tuple[int, str]] = []
    fenced = False
    for i, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            out.append((i, line))
    return out


def _resolves(target: Path) -> bool:
    """Whether a referenced path exists, INCLUDING as a module reference.

    `ml/inference_engine` is a perfectly ordinary way to name `ml/inference_engine.py`
    — dropping the extension is how module paths are written in prose, and both of
    the first version's findings in the constitution documents were exactly that.
    A checker that calls those stale is a checker that gets ignored on the two
    documents where being ignored costs most.
    """
    if target.exists():
        return True
    for suffix in (".py", ".ts", ".tsx", ".js", ".md", ".sh", ".yml", ".yaml", ".json", ".toml"):
        if target.with_name(target.name + suffix).exists():
            return True
    return (target / "__init__.py").exists()


def _quoted(line: str, start: int, end: int) -> bool:
    """Whether the span at [start:end) sits inside a quotation on this line.

    Counting quote characters before the span: an odd count means the span opened
    a quotation that has not closed, which is the reproduction of somebody else's
    wording rather than an assertion of this document's own.
    """
    for mark in ('"', "\u201c"):
        before = line[:start].count(mark) if mark == '"' else line[:start].count("\u201c")
        after = line[end:].count(mark) if mark == '"' else line[end:].count("\u201d")
        if before % 2 == 1 or (before >= 1 and after >= 1):
            return True
    return False


def _inside(path: Path, repo: Path) -> bool:
    """Whether `path` is within the repository, without raising when it is not."""
    try:
        path.resolve().relative_to(repo.resolve())
    except ValueError:
        return False
    return True


def _candidate_paths(line: str) -> list[str]:
    found: list[str] = []
    for span in _CODE_SPAN.findall(line):
        value = span.strip().rstrip(":,.;")
        if not _PATH_LIKE.match(value) or _PLACEHOLDER.search(value):
            continue
        if "/" not in value and Path(value).suffix not in _EXTENSIONS:
            continue
        found.append(value.rstrip("/"))
    return found


def _candidate_links(line: str) -> list[str]:
    out: list[str] = []
    for target in _MD_LINK.findall(line):
        if target.startswith(("http://", "https://", "mailto:", "#")) or _PLACEHOLDER.search(target):
            continue
        out.append(target)
    return out


def check_document(path: Path, repo: Path) -> list[Finding]:
    """Every checkable claim in one document that is now false."""
    # A document is normally inside the repository it makes claims about, but not
    # always: the gitignore rule needs a real work tree to check against, so a
    # caller may legitimately pass a probe document held elsewhere. Falling back
    # to the bare name keeps that a supported call rather than a crash.
    try:
        rel = path.relative_to(repo).as_posix()
    except ValueError:
        rel = path.name
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    findings: list[Finding] = []
    for lineno, line in _strip_fenced_blocks(text):
        # -- referential: paths ------------------------------------------------
        for candidate in _candidate_paths(line):
            if candidate.startswith("/"):
                # An absolute path is about the host, not this repository.
                continue
            target = repo / candidate
            if _resolves(target):
                continue
            # Only a claim if the parent exists AND is inside the repo. A `..`
            # sequence can walk out of the tree, and comparing a path outside it
            # against the repo root raises rather than returning False.
            parent = target.parent
            if not _inside(parent, repo):
                continue
            if _is_a_template(candidate):
                # `docs/decisions/NNNN-short-title.md` is a NAMING RULE, not a
                # reference. Group 3 Chapter 6 writes it that way on purpose, and
                # the moment docs/decisions/ existed this checker started calling
                # the rule a stale path — a false positive that arrives exactly
                # when the thing being specified gets built, which is the worst
                # possible timing for a gate people can silence.
                continue
            if _is_ignored(candidate, repo):
                # A path git itself refuses to track is a runtime-generated
                # artefact by construction — data/oanda_paper_start.json and
                # backtest/results/multi_symbol_report.json are legitimately
                # absent from a fresh checkout, and the doc referencing them
                # is describing real behaviour, not a stale path.
                continue
            if parent.exists() and parent != repo:
                findings.append(
                    Finding(
                        "stale_path",
                        rel,
                        lineno,
                        f"`{candidate}` does not exist, but `{parent.relative_to(repo).as_posix()}/` does",
                    )
                )

        # -- referential: links ------------------------------------------------
        for target_str in _candidate_links(line):
            target = (path.parent / target_str).resolve()
            if not target.exists():
                findings.append(Finding("broken_link", rel, lineno, f"link target {target_str!r} does not exist"))

        # -- claim: gitignore status -------------------------------------------
        for m in _GITIGNORE_CLAIM.finditer(line):
            if _REPORTING.search(line) or _quoted(line, m.start(), m.end()):
                # Same guard as the version rule. Applying it to only one of the
                # two claim rules was an inconsistency the checker itself found,
                # by firing on this module's own correction table.
                continue
            named, negated, word = m.group(1), bool(m.group("neg")), m.group("word").lower()
            if not (repo / named).exists():
                continue
            claimed_ignored = (word != "tracked") != negated
            actually_ignored = _is_ignored(named, repo)
            if claimed_ignored != actually_ignored:
                findings.append(
                    Finding(
                        "gitignore_claim",
                        rel,
                        lineno,
                        f"`{named}` is claimed {'ignored' if claimed_ignored else 'not ignored'} "
                        f"and is actually {'ignored' if actually_ignored else 'not ignored'}",
                    )
                )

        # -- claim: pinned interpreter version ---------------------------------
        if _PY_CONTEXT.search(line) and not _REPORTING.search(line):
            for m in _PY_VERSION_CLAIM.finditer(line):
                if _quoted(line, m.start(), m.end()):
                    # Quoted text is somebody else's sentence being reproduced.
                    continue
                stated = m.group(1)
                real = _dockerfile_python(repo)
                if real and stated != real:
                    findings.append(
                        Finding(
                            "python_version_claim",
                            rel,
                            lineno,
                            f"states Python {stated} as the target; the Dockerfile runs {real}",
                        )
                    )
    return findings


#: Tokens that mark a path as a pattern rather than a reference.
#:
#: `NNNN` and `X.Y` are the conventional stand-ins for "a number goes here";
#: angle and curly brackets are the conventional stand-ins for everything else.
#: A path containing one of these was never meant to resolve.
_TEMPLATE_TOKENS: Final[tuple[str, ...]] = ("NNNN", "<", ">", "{", "}", "*", "$")


def _is_a_template(candidate: str) -> bool:
    return any(token in candidate for token in _TEMPLATE_TOKENS)


def _is_ignored(relative: str, repo: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", relative],
        cwd=repo,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


_DOCKER_PY: list[str | None] = [None]


def _dockerfile_python(repo: Path) -> str | None:
    """The interpreter the production image actually runs. Read once."""
    if _DOCKER_PY[0] is not None:
        return _DOCKER_PY[0] or None
    dockerfile = repo / "Dockerfile"
    version = ""
    if dockerfile.exists():
        m = re.search(r"^FROM\s+python:(\d+\.\d+)", dockerfile.read_text(encoding="utf-8"), re.M)
        version = m.group(1) if m else ""
    _DOCKER_PY[0] = version
    return version or None


def load_baseline(path: Path | None = None) -> Baseline:
    target = path or BASELINE_PATH
    if not target.exists():
        return Baseline()
    data = tomllib.loads(target.read_text(encoding="utf-8"))
    return Baseline(adopted=data.get("adopted", ""), known=list(data.get("known", [])))


def dump_baseline(baseline: Baseline) -> str:
    header = (
        "# Freshness baseline — Group 3 Chapter 15. The ratchet.\n"
        "#\n"
        "# Findings that already existed when the check was adopted. A NEW finding\n"
        "# blocks; these do not. Removing a line here is how the debt is paid down,\n"
        "# and a line whose finding is fixed must be removed or it hides a recurrence.\n"
        "#\n"
        "# Regenerate:  python scripts/docs_freshness.py --adopt\n"
        "# Check:       python scripts/docs_freshness.py --check\n\n"
    )
    lines = [f'adopted = "{baseline.adopted}"', "known = ["]
    lines += [f'  "{k}",' for k in sorted(baseline.known)]
    lines.append("]")
    return header + "\n".join(lines) + "\n"


def checkable_documents(base: Path) -> list[str]:
    """The documents where a stale reference is a DEFECT rather than a fact.

    Scoped by the registry from Group 3 Chapter 2 — the two phases composing, which
    is what the registry was for. Only the authority tiers are checked:

    * **T0/T1/T2** are living. A reference that has gone stale in one of them
      misleads a reader who is right to trust it.
    * **T3** records are immutable and correct at their date. A postmortem naming
      a file that later moved is still an accurate record of what was true then;
      "fixing" it would destroy the record.
    * **T4** is archived or working material, explicitly no longer maintained.

    Measured: 172 of the first 250 findings were in `docs/archive/`. Reporting
    those every run would bury the ones that matter under debt nobody intends to
    pay, and a report nobody reads is a check nobody runs.
    """
    from scripts.docs_registry import AUTHORITY_TIERS, discover, load

    entries, _ = load()
    tier_by_path = {e.path: e.tier for e in entries}
    on_disk = discover(base)
    # A document with no registry entry is checked: unknown is not exempt.
    return [rel for rel in on_disk if rel.endswith(".md") and tier_by_path.get(rel, "T2") in AUTHORITY_TIERS]


def check_all(repo: Path | None = None, baseline: Baseline | None = None) -> list[Finding]:
    base = repo or REPO
    bl = baseline if baseline is not None else load_baseline()
    known = set(bl.known)
    findings: list[Finding] = []

    for rel in checkable_documents(base):
        for f in check_document(base / rel, base):
            f.blocking = f.key() not in known
            findings.append(f)
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Documentation freshness: referential and claim checks.")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--adopt", action="store_true", help="Baseline every current finding (once)")
    parser.add_argument("--show-baselined", action="store_true", help="Also print baselined findings")
    args = parser.parse_args(argv)

    if args.adopt:
        from datetime import date

        findings = check_all(baseline=Baseline())
        bl = Baseline(adopted=date.today().isoformat(), known=sorted({f.key() for f in findings}))
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(dump_baseline(bl), encoding="utf-8")
        print(f"freshness: baselined {len(bl.known)} existing findings")
        return 0

    findings = check_all()
    blocking = [f for f in findings if f.blocking]
    for f in findings:
        if f.blocking or args.show_baselined:
            tag = "FAIL" if f.blocking else "note"
            print(f"{tag}  [{f.rule}] {f.document}:{f.line}  {f.detail}")
    print(f"\n{len(blocking)} blocking, {len(findings) - len(blocking)} baselined")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
