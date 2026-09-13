# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The schema-migration gate must be able to fail, and must not cry wolf.

F218: *"36 of 44 tables have no migration"*. Measured with names resolved rather
than matched as text, it is **0 of 47** — and the 47 includes three tables in
`database/user_models.py` that the original probe never looked at.

The 36 came from searching migration text for

    create_table(  "table_name"

which this repository does not write. Three ways that misses:

* **the idempotency wrapper** — nearly every migration defines a local
  `_tbl(name, *args, **kwargs)` that calls `op.create_table` only when the table
  is absent, so an upgrade can be re-run. 35 of 43 tables go through it and the
  literal never sits beside `create_table`;
* **module-level constants** — `ai_department_memory`, `sessions`,
  `support_tickets` and `support_messages` are created as
  `op.create_table(_TABLE, ...)`;
* **a second models module**, not scanned at all.

A probe that reports 32 false positives is worse than no probe: a real gap is
invisible in the noise, and the number gets quoted in three documents. So this
suite is in two halves, and the second matters as much as the first.

**It can fail** — a table added to the ORM with no migration is refused, in
either models file, and the scan fails closed if it matches nothing.

**It does not cry wolf** — each of the three real-world declaration styles is
exercised against a throwaway tree and must be recognised.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "schema_migration_check.py"


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    # `--root` rather than cwd: the script resolves its repository explicitly,
    # so it can be exercised against a throwaway tree. Rooting it at `__file__`
    # meant every injection below silently audited the real repository and
    # passed — which is how this suite first "went green".
    extra = ["--root", str(cwd)] if cwd is not None else []
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, *extra],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,  # inspecting non-zero exits is the point
    )


# ── The real repository ───────────────────────────────────────────────────────


def test_every_orm_table_has_a_migration():
    result = run("--check")
    assert result.returncode == 0, result.stderr


def test_the_scan_finds_both_model_modules():
    """`database/user_models.py` holds three tables the first probe never saw."""
    sys.path.insert(0, str(REPO / "scripts"))
    import schema_migration_check as smc

    declared = smc.declared_tables()
    assert len(declared) >= 45, f"only {len(declared)} tables found — the scan is wrong"
    for name in ("users", "user_sessions", "login_attempts"):
        assert name in declared, f"{name} is missing — database/user_models.py is not being read"
    assert any(v.endswith("user_models.py") for v in declared.values())


def test_the_idempotency_wrapper_is_followed():
    """35 of 43 tables are created through `_tbl`, not `create_table` directly."""
    sys.path.insert(0, str(REPO / "scripts"))
    import schema_migration_check as smc

    created = smc.migrated_tables()
    assert len(created) >= 40, f"only {len(created)} creations found — the wrapper is not being followed"


# ── Injections, against a throwaway tree ──────────────────────────────────────


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A miniature repo whose migrations use all three declaration styles."""
    (tmp_path / "database").mkdir()
    (tmp_path / "alembic" / "versions").mkdir(parents=True)

    (tmp_path / "database" / "models.py").write_text(
        textwrap.dedent(
            """
            class Alpha(Base):
                __tablename__ = "alpha"

            class Beta(Base):
                __tablename__ = "beta"

            class Gamma(Base):
                __tablename__ = "gamma"
            """
        ).strip()
        + "\n"
    )
    (tmp_path / "database" / "user_models.py").write_text('class Delta(Base):\n    __tablename__ = "delta"\n')

    # Style 1: a plain literal.
    (tmp_path / "alembic" / "versions" / "001_alpha.py").write_text(
        'def upgrade():\n    op.create_table("alpha", sa.Column("id"))\n'
    )
    # Style 2: the idempotency wrapper.
    (tmp_path / "alembic" / "versions" / "002_beta.py").write_text(
        textwrap.dedent(
            """
            def upgrade():
                def _tbl(name, *args, **kwargs):
                    if name not in existing:
                        op.create_table(name, *args, **kwargs)

                _tbl("beta", sa.Column("id"))
            """
        ).strip()
        + "\n"
    )
    # Style 3: a module-level constant.
    (tmp_path / "alembic" / "versions" / "003_gamma.py").write_text(
        '_TABLE = "gamma"\n\n\ndef upgrade():\n    op.create_table(_TABLE, sa.Column("id"))\n'
    )
    (tmp_path / "alembic" / "versions" / "004_delta.py").write_text(
        'def upgrade():\n    op.create_table("delta", sa.Column("id"))\n'
    )
    return tmp_path


def test_all_three_declaration_styles_are_recognised(project: Path):
    """The half that keeps this usable. Two of the three defeated the old probe."""
    result = run("--check", cwd=project)
    assert result.returncode == 0, f"a legitimate declaration style was not recognised:\n{result.stderr}"


def test_a_table_with_no_migration_blocks(project: Path):
    """The injection."""
    models = project / "database" / "models.py"
    models.write_text(models.read_text() + '\n\nclass Epsilon(Base):\n    __tablename__ = "epsilon"\n')

    result = run("--check", cwd=project)
    assert result.returncode == 1, "a table with no migration must block"
    assert "epsilon" in result.stderr
    assert "create_all() creates what is missing and never ALTERs" in result.stderr


def test_a_table_added_to_the_second_models_module_also_blocks(project: Path):
    """The module the original probe ignored is not a blind spot here."""
    user_models = project / "database" / "user_models.py"
    user_models.write_text(user_models.read_text() + '\n\nclass Zeta(Base):\n    __tablename__ = "zeta"\n')

    result = run("--check", cwd=project)
    assert result.returncode == 1
    assert "zeta" in result.stderr
    assert "user_models.py" in result.stderr


def test_removing_a_migration_blocks(project: Path):
    """The test F218 asks for by name: remove one and watch it fail."""
    (project / "alembic" / "versions" / "002_beta.py").unlink()

    result = run("--check", cwd=project)
    assert result.returncode == 1
    assert "beta" in result.stderr


def test_a_scan_that_finds_no_tables_fails_closed(tmp_path: Path):
    """F255: a scan that matched nothing must not certify a tree it never read."""
    (tmp_path / "database").mkdir()
    (tmp_path / "alembic" / "versions").mkdir(parents=True)

    result = run("--check", cwd=tmp_path)
    assert result.returncode == 1
    assert "scan is broken" in result.stderr


def test_a_scan_that_finds_no_migrations_fails_closed(tmp_path: Path):
    """The other half: tables but no migrations at all is a broken scan, not a pass."""
    (tmp_path / "database").mkdir()
    (tmp_path / "alembic" / "versions").mkdir(parents=True)
    (tmp_path / "database" / "models.py").write_text('class A(Base):\n    __tablename__ = "a"\n')

    result = run("--check", cwd=tmp_path)
    assert result.returncode == 1
    assert "scan is broken" in result.stderr
