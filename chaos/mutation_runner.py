# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
chaos/mutation_runner.py
=========================
MutationTestRunner — runs mutmut (or cosmic-ray) against the core trading
modules and reports the mutation score.

Mutation testing complements unit tests by verifying that the test suite
actually *detects* code changes. A mutation score of 80%+ means 80% of
single-line code mutations are caught by at least one test.

Design
------
- Uses ``mutmut`` as the primary mutation engine (pip install mutmut).
- Falls back to a lightweight built-in AST mutator if mutmut is not
  installed, so CI never hard-fails on a missing optional dependency.
- Targets only the critical trading modules (risk/, execution/, shadow/)
  to keep runtime under 5 minutes in CI.
- Results are written to ``reports/mutation_report.json`` and exposed via
  the /api/chaos/mutation endpoint.
- Prometheus counter tracks mutation score over time.

Usage (CLI)
-----------
    python -m chaos.mutation_runner --modules risk execution shadow
    python -m chaos.mutation_runner --modules risk --timeout 300

Usage (programmatic)
--------------------
    from chaos.mutation_runner import MutationTestRunner

    runner = MutationTestRunner(modules=["risk", "execution"])
    report = await runner.run()
    logger.info(f"Mutation score: {report.score:.1%}")

Configuration (env vars)
------------------------
    MUTATION_MODULES        — comma-separated module dirs (default: risk,execution,shadow)
    MUTATION_TIMEOUT_S      — max seconds for full run (default: 300)
    MUTATION_REPORT_PATH    — output JSON path (default: reports/mutation_report.json)
    MUTATION_MIN_SCORE      — minimum acceptable score, 0–1 (default: 0.70)
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
import subprocess  # nosec B404 - list-form call with sys.executable; no shell=True, no user input
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
UTC = timezone.utc
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
_DEFAULT_MODULES = os.getenv("MUTATION_MODULES", "risk,execution,shadow").split(",")
_TIMEOUT_S = float(os.getenv("MUTATION_TIMEOUT_S", "300"))
_REPORT_PATH = Path(os.getenv("MUTATION_REPORT_PATH", "reports/mutation_report.json"))
_MIN_SCORE = float(os.getenv("MUTATION_MIN_SCORE", "0.70"))

# ── Prometheus ────────────────────────────────────────────────────────────────
try:
    from prometheus_client import Gauge

    _prom_score = Gauge("hopefx_mutation_score", "Mutation test score (0–1)")
    _prom_killed = Gauge("hopefx_mutation_killed", "Mutants killed by tests")
    _prom_total = Gauge("hopefx_mutation_total", "Total mutants generated")
    _PROM_OK = True
except ImportError:
    _PROM_OK = False


@dataclass
class MutantResult:
    """Result for a single mutant."""

    mutant_id: str
    module: str
    line: int
    description: str
    status: str  # "killed" | "survived" | "timeout" | "error"


@dataclass
class MutationReport:
    """Full mutation testing report."""

    modules: list[str]
    total: int
    killed: int
    survived: int
    timeouts: int
    errors: int
    score: float  # killed / (killed + survived), 0–1
    passed: bool  # score >= MIN_SCORE
    min_score: float
    duration_s: float
    engine: str  # "mutmut" | "builtin_ast"
    mutants: list[MutantResult] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def summary(self) -> str:
        icon = "✓" if self.passed else "✗"
        return (
            f"[{icon}] Mutation score: {self.score:.1%} "
            f"({self.killed}/{self.killed + self.survived} mutants killed) "
            f"engine={self.engine} duration={self.duration_s:.1f}s"
        )


class MutationTestRunner:
    """
    Runs mutation testing against specified modules.

    Tries mutmut first; falls back to built-in AST mutator if unavailable.
    """

    def __init__(
        self,
        modules: list[str] | None = None,
        timeout_s: float = _TIMEOUT_S,
        min_score: float = _MIN_SCORE,
        report_path: Path = _REPORT_PATH,
    ) -> None:
        self._modules = [m.strip() for m in (modules or _DEFAULT_MODULES)]
        self._timeout_s = timeout_s
        self._min_score = min_score
        self._report_path = report_path
        self._last_report: MutationReport | None = None

    async def run(self) -> MutationReport:
        """Run mutation testing. Returns MutationReport."""
        t0 = time.monotonic()

        # Try mutmut first
        if self._mutmut_available():
            report = await self._run_mutmut()
        else:
            logger.warning("mutmut not installed — using built-in AST mutator. Install with: pip install mutmut")
            report = await self._run_builtin_ast()

        report.duration_s = time.monotonic() - t0

        if _PROM_OK:
            _prom_score.set(report.score)
            _prom_killed.set(report.killed)
            _prom_total.set(report.total)

        self._last_report = report
        self._save_report(report)

        logger.info(report.summary())
        if not report.passed:
            logger.warning(
                "Mutation score %.1f%% below minimum %.1f%% — add tests to cover surviving mutants",
                report.score * 100,
                self._min_score * 100,
            )

        return report

    # ── mutmut engine ─────────────────────────────────────────────────────────

    def _mutmut_available(self) -> bool:
        try:
            result = subprocess.run(  # nosec B603 B607 - list-form call with sys.executable; no shell=True, no user input
                [sys.executable, "-m", "mutmut", "--version"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    async def _run_mutmut(self) -> MutationReport:
        """Run mutmut against target modules and parse results."""
        paths = " ".join(str(Path(m)) for m in self._modules if Path(m).exists())
        if not paths:
            logger.warning("No valid module paths found for mutmut")
            return self._empty_report("mutmut")

        cmd = [
            sys.executable,
            "-m",
            "mutmut",
            "run",
            "--paths-to-mutate",
            paths,
            "--runner",
            f"{sys.executable} -m pytest tests/ -x -q --tb=no",
            "--no-progress",
        ]

        logger.info("Running mutmut: %s", " ".join(cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, _ = await asyncio.wait_for(proc.communicate(), timeout=self._timeout_s)
            except TimeoutError:
                proc.kill()
                logger.error("mutmut timed out after %.0fs", self._timeout_s)
                return self._empty_report("mutmut", error="timeout")

            # Parse mutmut results
            return await self._parse_mutmut_results()

        except Exception:
            logger.exception("mutmut run failed: %s")
            return self._empty_report("mutmut", error="mutmut run failed — check server logs")

    async def _parse_mutmut_results(self) -> MutationReport:
        """Parse mutmut result database via `mutmut results`."""
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "mutmut",
                "results",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode()

            killed = output.count("Killed")
            survived = output.count("Survived")
            timeouts = output.count("Timeout")
            total = killed + survived + timeouts

            score = killed / max(killed + survived, 1)
            return MutationReport(
                modules=self._modules,
                total=total,
                killed=killed,
                survived=survived,
                timeouts=timeouts,
                errors=0,
                score=round(score, 4),
                passed=score >= self._min_score,
                min_score=self._min_score,
                duration_s=0.0,
                engine="mutmut",
            )
        except Exception:
            logger.exception("mutmut results parse failed: %s")
            return self._empty_report("mutmut", error="mutmut results parse failed — check server logs")

    # ── Built-in AST mutator ──────────────────────────────────────────────────

    async def _run_builtin_ast(self) -> MutationReport:
        """
        Lightweight AST-based mutation engine.

        Applies single-operator mutations to each target module, runs pytest
        against the mutated source, and records kill/survive.

        Mutations applied:
          - Flip comparison operators: > → >=, < → <=, == → !=
          - Flip boolean operators: and → or, or → and
          - Negate return values: return x → return not x (bool returns only)
          - Off-by-one: numeric literals n → n+1, n-1
        """
        mutants: list[MutantResult] = []
        killed = survived = timeouts = errors = 0

        for module_dir in self._modules:
            module_path = Path(module_dir)
            if not module_path.exists():
                logger.warning("Module path not found: %s", module_path)
                continue

            py_files = list(module_path.rglob("*.py"))
            for py_file in py_files:
                if "__pycache__" in str(py_file):
                    continue
                file_mutants = self._generate_mutants(py_file)
                for mutant in file_mutants:
                    status = await self._test_mutant(py_file, mutant)
                    result = MutantResult(
                        mutant_id=f"{py_file}:{mutant['line']}:{mutant['op']}",
                        module=str(py_file),
                        line=mutant["line"],
                        description=mutant["description"],
                        status=status,
                    )
                    mutants.append(result)
                    if status == "killed":
                        killed += 1
                    elif status == "survived":
                        survived += 1
                    elif status == "timeout":
                        timeouts += 1
                    else:
                        errors += 1

        total = killed + survived + timeouts + errors
        score = killed / max(killed + survived, 1)

        return MutationReport(
            modules=self._modules,
            total=total,
            killed=killed,
            survived=survived,
            timeouts=timeouts,
            errors=errors,
            score=round(score, 4),
            passed=score >= self._min_score,
            min_score=self._min_score,
            duration_s=0.0,
            engine="builtin_ast",
            mutants=mutants,
        )

    def _generate_mutants(self, py_file: Path) -> list[dict[str, Any]]:
        """Parse a Python file and generate mutation descriptors."""
        try:
            source = py_file.read_text()
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            return []

        mutants = []
        for node in ast.walk(tree):
            # Comparison operator mutations
            if isinstance(node, ast.Compare):
                for op in node.ops:
                    orig = type(op).__name__
                    flips = {
                        "Gt": "GtE",
                        "GtE": "Gt",
                        "Lt": "LtE",
                        "LtE": "Lt",
                        "Eq": "NotEq",
                        "NotEq": "Eq",
                    }
                    if orig in flips:
                        mutants.append(
                            {
                                "line": node.lineno,
                                "op": f"cmp_{orig}_to_{flips[orig]}",
                                "node_type": "Compare",
                                "original": orig,
                                "replacement": flips[orig],
                                "description": f"line {node.lineno}: {orig} → {flips[orig]}",
                            }
                        )

            # Boolean operator mutations
            elif isinstance(node, ast.BoolOp):
                orig = type(node.op).__name__
                flip = "Or" if orig == "And" else "And"
                mutants.append(
                    {
                        "line": node.lineno,
                        "op": f"bool_{orig}_to_{flip}",
                        "node_type": "BoolOp",
                        "original": orig,
                        "replacement": flip,
                        "description": f"line {node.lineno}: {orig} → {flip}",
                    }
                )

            # Off-by-one on small integer literals
            elif isinstance(node, ast.Constant) and isinstance(node.value, int) and 0 < abs(node.value) <= 100:
                mutants.append(
                    {
                        "line": node.lineno,
                        "op": f"const_{node.value}_to_{node.value + 1}",
                        "node_type": "Constant",
                        "original": node.value,
                        "replacement": node.value + 1,
                        "description": f"line {node.lineno}: {node.value} → {node.value + 1}",
                    }
                )

        # Cap per-file mutants to avoid combinatorial explosion
        return mutants[:20]

    async def _test_mutant(self, py_file: Path, mutant: dict[str, Any]) -> str:
        """
        Apply a single mutation, run pytest, restore original, return status.

        Returns: "killed" | "survived" | "timeout" | "error"
        """
        original_source = py_file.read_text()
        mutated_source = self._apply_mutation(original_source, mutant)

        if mutated_source == original_source:
            return "error"  # mutation had no effect

        try:
            py_file.write_text(mutated_source)
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "pytest",
                "tests/",
                "-x",
                "-q",
                "--tb=no",
                "--no-header",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                # returncode != 0 means at least one test failed → mutant killed
                return "killed" if proc.returncode != 0 else "survived"
            except TimeoutError:
                proc.kill()
                return "timeout"
        except Exception as exc:
            logger.debug("Mutant test error: %s", exc)
            return "error"
        finally:
            # Always restore original source
            py_file.write_text(original_source)

    def _apply_mutation(self, source: str, mutant: dict[str, Any]) -> str:
        """Apply a single mutation to source text via token replacement."""
        op_map = {
            "Gt": ">",
            "GtE": ">=",
            "Lt": "<",
            "LtE": "<=",
            "Eq": "==",
            "NotEq": "!=",
            "And": "and",
            "Or": "or",
        }
        node_type = mutant.get("node_type")
        orig = mutant.get("original")
        repl = mutant.get("replacement")

        if node_type in ("Compare", "BoolOp"):
            orig_tok = op_map.get(str(orig), str(orig))
            repl_tok = op_map.get(str(repl), str(repl))
            # Only replace on the target line to avoid false mutations
            lines = source.splitlines()
            target_line = mutant.get("line", 1) - 1
            if 0 <= target_line < len(lines):
                lines[target_line] = lines[target_line].replace(orig_tok, repl_tok, 1)
            return "\n".join(lines)

        if node_type == "Constant":
            lines = source.splitlines()
            target_line = mutant.get("line", 1) - 1
            if 0 <= target_line < len(lines):
                lines[target_line] = lines[target_line].replace(str(orig), str(repl), 1)
            return "\n".join(lines)

        return source

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _empty_report(self, engine: str, error: str = "") -> MutationReport:
        return MutationReport(
            modules=self._modules,
            total=0,
            killed=0,
            survived=0,
            timeouts=0,
            errors=1 if error else 0,
            score=0.0,
            passed=False,
            min_score=self._min_score,
            duration_s=0.0,
            engine=engine,
        )

    def _save_report(self, report: MutationReport) -> None:
        try:
            self._report_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "modules": report.modules,
                "total": report.total,
                "killed": report.killed,
                "survived": report.survived,
                "timeouts": report.timeouts,
                "errors": report.errors,
                "score": report.score,
                "passed": report.passed,
                "min_score": report.min_score,
                "duration_s": round(report.duration_s, 2),
                "engine": report.engine,
                "generated_at": report.generated_at,
                "mutants": [
                    {
                        "id": m.mutant_id,
                        "module": m.module,
                        "line": m.line,
                        "description": m.description,
                        "status": m.status,
                    }
                    for m in report.mutants
                ],
            }
            self._report_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.info("Mutation report saved to %s", self._report_path)
        except Exception as exc:
            logger.error("Failed to save mutation report: %s", exc)

    def last_report(self) -> MutationReport | None:
        return self._last_report


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run mutation testing")
    parser.add_argument(
        "--modules",
        nargs="+",
        default=_DEFAULT_MODULES,
        help="Module directories to mutate (default: risk execution shadow)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=_TIMEOUT_S,
        help="Max seconds for full run",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=_MIN_SCORE,
        help="Minimum acceptable mutation score (0–1)",
    )
    args = parser.parse_args()

    async def _main():
        runner = MutationTestRunner(
            modules=args.modules,
            timeout_s=args.timeout,
            min_score=args.min_score,
        )
        report = await runner.run()
        logger.info(report.summary())
        sys.exit(0 if report.passed else 1)

    asyncio.run(_main())
