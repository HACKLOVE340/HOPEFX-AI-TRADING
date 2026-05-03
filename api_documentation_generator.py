# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
api_documentation_generator.py
================================
Generates OpenAPI-based documentation for the HOPEFX API.

Usage:
    python api_documentation_generator.py [--output docs/api.json] [--format json|yaml|markdown]

Outputs:
    - docs/api.json        — OpenAPI 3.1 JSON schema
    - docs/api.yaml        — OpenAPI 3.1 YAML schema
    - docs/api.md          — Markdown reference (endpoint table + descriptions)

The generator imports the FastAPI app, extracts the OpenAPI schema, and writes
the output files.  It does not start the server.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ── Output paths ──────────────────────────────────────────────────────────────

DOCS_DIR = Path(__file__).parent / "docs"
DEFAULT_JSON = DOCS_DIR / "api.json"
DEFAULT_YAML = DOCS_DIR / "api.yaml"
DEFAULT_MD = DOCS_DIR / "api.md"


# ── OpenAPI extraction ────────────────────────────────────────────────────────

def get_openapi_schema() -> dict:
    """Import the FastAPI app and return its OpenAPI schema dict."""
    # Add project root to path so imports resolve
    project_root = str(Path(__file__).parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    try:
        from main import app  # type: ignore[import]
        schema = app.openapi()
        return schema
    except Exception as exc:
        logger.warning("Could not import main.app (%s) — building minimal schema", exc)
        return _minimal_schema()


def _minimal_schema() -> dict:
    """Return a minimal OpenAPI schema by scanning api/ for router files."""
    project_root = Path(__file__).parent
    api_dir = project_root / "api"

    paths: dict = {}
    tags: list[dict] = []

    # Scan all api/*.py files for @router decorators
    for py_file in sorted(api_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        tag = py_file.stem.replace("_", "-")
        tags.append({"name": tag, "description": f"Endpoints from api/{py_file.name}"})
        try:
            src = py_file.read_text(encoding="utf-8")
            for line in src.splitlines():
                line = line.strip()
                for method in ("get", "post", "put", "patch", "delete"):
                    prefix = f'@router.{method}("'
                    if line.startswith(prefix):
                        path_part = line[len(prefix):].split('"')[0]
                        full_path = f"/api/{tag}{path_part}"
                        paths.setdefault(full_path, {})[method] = {
                            "tags": [tag],
                            "summary": path_part,
                            "responses": {"200": {"description": "OK"}},
                        }
        except Exception:  # nosec B110
            pass

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "HOPEFX AI Trading API",
            "version": "1.0.0",
            "description": (
                "Production REST API for the HOPEFX AI Trading platform. "
                "All endpoints require JWT authentication unless noted."
            ),
            "contact": {"name": "HOPEFX", "url": "https://github.com/HACKLOVE340/HOPEFX-AI-TRADING"},
            "license": {"name": "AGPL-3.0", "url": "https://www.gnu.org/licenses/agpl-3.0.html"},
        },
        "paths": paths,
        "tags": tags,
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                }
            }
        },
        "security": [{"BearerAuth": []}],
    }


# ── Writers ───────────────────────────────────────────────────────────────────

def write_json(schema: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2, default=str), encoding="utf-8")
    logger.info("Wrote %s", path)


def write_yaml(schema: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml  # type: ignore[import]
        path.write_text(yaml.dump(schema, allow_unicode=True, sort_keys=False), encoding="utf-8")
        logger.info("Wrote %s", path)
    except ImportError:
        logger.warning("PyYAML not installed — skipping YAML output (pip install pyyaml)")


def write_markdown(schema: dict, path: Path) -> None:
    """Write a Markdown reference table from the OpenAPI schema."""
    path.parent.mkdir(parents=True, exist_ok=True)
    info = schema.get("info", {})
    paths = schema.get("paths", {})

    lines: list[str] = [
        f"# {info.get('title', 'API Reference')}",
        "",
        f"**Version:** {info.get('version', 'unknown')}",
        "",
        info.get("description", ""),
        "",
        "## Endpoints",
        "",
        "| Method | Path | Summary | Tags |",
        "|--------|------|---------|------|",
    ]

    for endpoint_path, methods in sorted(paths.items()):
        for method, op in methods.items():
            if not isinstance(op, dict):
                continue
            summary = op.get("summary", "")
            tags = ", ".join(op.get("tags", []))
            lines.append(f"| `{method.upper()}` | `{endpoint_path}` | {summary} | {tags} |")

    lines += [
        "",
        "## Authentication",
        "",
        "All endpoints require a JWT Bearer token unless marked public.",
        "",
        "```",
        "Authorization: Bearer <token>",
        "```",
        "",
        "## Rate Limiting",
        "",
        "The API gateway enforces per-IP sliding-window rate limits.",
        "Exceeding the limit returns HTTP 429.",
        "",
        "---",
        f"*Generated by api_documentation_generator.py*",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate HOPEFX API documentation")
    parser.add_argument("--output-dir", default=str(DOCS_DIR), help="Output directory (default: docs/)")
    parser.add_argument(
        "--format",
        choices=["json", "yaml", "markdown", "all"],
        default="all",
        help="Output format (default: all)",
    )
    parser.add_argument(
        "--no-import",
        action="store_true",
        help="Skip importing the FastAPI app (use minimal schema scanner instead)",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir)

    if args.no_import:
        schema = _minimal_schema()
    else:
        schema = get_openapi_schema()

    fmt = args.format
    if fmt in ("json", "all"):
        write_json(schema, out_dir / "api.json")
    if fmt in ("yaml", "all"):
        write_yaml(schema, out_dir / "api.yaml")
    if fmt in ("markdown", "all"):
        write_markdown(schema, out_dir / "api.md")

    endpoint_count = sum(
        len([m for m in methods if isinstance(methods[m], dict)])
        for methods in schema.get("paths", {}).values()
    )
    logger.info("Documentation generated: %d endpoints documented", endpoint_count)


if __name__ == "__main__":
    main()
