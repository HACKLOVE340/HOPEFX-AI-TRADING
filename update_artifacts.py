#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
update_artifacts.py
====================
Regenerate assets/cover.png from real ML training report data.

Reads ml/saved_models/training_report.json (and optionally
ml/saved_models/advanced_training_report.json) and renders a
1280×640 cover image showing live model metrics.

Usage:
    python update_artifacts.py [--output assets/cover.png]

Called by .github/workflows/update_docs.yml on every push that
touches the training reports, README, or this script itself.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pillow is the only dependency — it is installed in the CI job.
# ---------------------------------------------------------------------------
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    logger.error("ERROR: Pillow is required. Install with: pip install Pillow", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent
TRAINING_REPORT = REPO_ROOT / "ml" / "saved_models" / "training_report.json"
ADVANCED_REPORT = REPO_ROOT / "ml" / "saved_models" / "advanced_training_report.json"

# ---------------------------------------------------------------------------
# Design constants
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 1280, 640
BG_COLOR = (10, 14, 26)  # deep navy
ACCENT = (255, 180, 0)  # gold
ACCENT2 = (0, 200, 150)  # teal
TEXT_PRIMARY = (240, 240, 255)  # near-white
TEXT_SECONDARY = (160, 170, 200)  # muted blue-grey
GRID_COLOR = (30, 40, 60)  # subtle grid lines
PASS_COLOR = (0, 210, 120)  # green for passing metrics
WARN_COLOR = (255, 160, 0)  # amber for borderline
FAIL_COLOR = (220, 60, 60)  # red for failing


def _load_report(path: Path) -> dict:
    """Load a JSON training report; return empty dict if missing."""
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _metric_color(value: float, threshold: float, higher_is_better: bool = True) -> tuple:
    """Return a colour based on whether a metric passes its threshold."""
    if higher_is_better:
        return PASS_COLOR if value >= threshold else WARN_COLOR
    return PASS_COLOR if value <= threshold else WARN_COLOR


def _try_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a system font at the requested size, falling back to default."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf" if bold else "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def generate_cover(output_path: Path) -> None:
    """Render the cover image and write it to *output_path*."""
    report = _load_report(TRAINING_REPORT)
    # Advanced report reserved for future metric panels
    _adv_report = _load_report(ADVANCED_REPORT)

    # ------------------------------------------------------------------
    # Extract metrics from the real training report
    # ------------------------------------------------------------------
    symbol = report.get("symbol", "XAUUSD")
    feature_count = report.get("feature_count", 0)
    sample_count = report.get("sample_count", 0)
    trained_at_raw = report.get("trained_at", "")
    try:
        trained_at = datetime.fromisoformat(trained_at_raw).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        trained_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    wf_xgb = report.get("walkforward_xgb", {})
    wf_rf = report.get("walkforward_rf", {})
    final_xgb = report.get("final_xgb", {})
    final_rf = report.get("final_rf", {})

    xgb_acc = final_xgb.get("accuracy", 0.0)
    xgb_f1 = final_xgb.get("f1", 0.0)
    rf_acc = final_rf.get("accuracy", 0.0)
    rf_f1 = final_rf.get("f1", 0.0)
    wf_xgb_sharpe = wf_xgb.get("mean_sharpe", 0.0)
    wf_rf_sharpe = wf_rf.get("mean_sharpe", 0.0) if wf_rf else 0.0
    wf_xgb_acc = wf_xgb.get("mean_accuracy", 0.0)
    wf_xgb_sig = wf_xgb.get("significant", False)

    # Walk-forward fold Sharpe values for the sparkline
    folds = wf_xgb.get("folds", [])
    fold_sharpes = [f.get("sharpe", 0.0) for f in folds]

    # ------------------------------------------------------------------
    # Canvas
    # ------------------------------------------------------------------
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Background grid
    for x in range(0, WIDTH, 80):
        draw.line([(x, 0), (x, HEIGHT)], fill=GRID_COLOR, width=1)
    for y in range(0, HEIGHT, 80):
        draw.line([(0, y), (WIDTH, y)], fill=GRID_COLOR, width=1)

    # Gold accent bar at top
    draw.rectangle([(0, 0), (WIDTH, 6)], fill=ACCENT)

    # ------------------------------------------------------------------
    # Fonts
    # ------------------------------------------------------------------
    font_title = _try_font(52, bold=True)
    font_subtitle = _try_font(22)
    font_label = _try_font(16)
    font_value = _try_font(32, bold=True)
    font_small = _try_font(14)

    # ------------------------------------------------------------------
    # Title block (left column)
    # ------------------------------------------------------------------
    draw.text((60, 40), "HOPEFX", font=font_title, fill=ACCENT)
    draw.text((60, 100), "AI Gold Trading Platform", font=font_subtitle, fill=TEXT_PRIMARY)
    draw.text(
        (60, 132),
        f"Symbol: {symbol}  ·  Features: {feature_count}  ·  Samples: {sample_count}",
        font=font_label,
        fill=TEXT_SECONDARY,
    )
    draw.text((60, 154), f"Last trained: {trained_at}", font=font_label, fill=TEXT_SECONDARY)

    # Teal accent line under title
    draw.rectangle([(60, 178), (420, 181)], fill=ACCENT2)

    # ------------------------------------------------------------------
    # Metric cards (two rows × three columns)
    # ------------------------------------------------------------------
    cards = [
        ("XGB Accuracy", f"{xgb_acc:.1%}", _metric_color(xgb_acc, 0.55)),
        ("XGB F1", f"{xgb_f1:.3f}", _metric_color(xgb_f1, 0.58)),
        ("WF XGB Sharpe", f"{wf_xgb_sharpe:+.3f}", _metric_color(wf_xgb_sharpe, 0.0)),
        ("RF Accuracy", f"{rf_acc:.1%}", _metric_color(rf_acc, 0.55)),
        ("RF F1", f"{rf_f1:.3f}", _metric_color(rf_f1, 0.58)),
        ("WF Significant", "YES" if wf_xgb_sig else "NO", PASS_COLOR if wf_xgb_sig else WARN_COLOR),
    ]

    card_w, card_h = 180, 90
    card_x0, card_y0 = 60, 210
    gap_x, gap_y = 20, 16

    for i, (label, value, color) in enumerate(cards):
        col = i % 3
        row = i // 3
        cx = card_x0 + col * (card_w + gap_x)
        cy = card_y0 + row * (card_h + gap_y)
        # Card background
        draw.rectangle([(cx, cy), (cx + card_w, cy + card_h)], fill=(20, 28, 48), outline=(40, 55, 90), width=1)
        # Colour accent strip
        draw.rectangle([(cx, cy), (cx + 4, cy + card_h)], fill=color)
        draw.text((cx + 14, cy + 10), label, font=font_small, fill=TEXT_SECONDARY)
        draw.text((cx + 14, cy + 32), value, font=font_value, fill=color)

    # ------------------------------------------------------------------
    # Walk-forward Sharpe sparkline (right panel)
    # ------------------------------------------------------------------
    spark_x0, spark_y0 = 700, 200
    spark_w, spark_h = 520, 200

    draw.rectangle(
        [(spark_x0, spark_y0), (spark_x0 + spark_w, spark_y0 + spark_h)],
        fill=(15, 22, 40),
        outline=(40, 55, 90),
        width=1,
    )
    draw.text((spark_x0 + 16, spark_y0 + 10), "Walk-Forward XGB Sharpe by Fold", font=font_label, fill=TEXT_SECONDARY)

    if fold_sharpes:
        min_s = min(fold_sharpes)
        max_s = max(fold_sharpes)
        span = max_s - min_s if max_s != min_s else 1.0
        n = len(fold_sharpes)
        bar_w = max(8, (spark_w - 40) // n - 4)
        zero_y = (
            spark_y0 + spark_h - 30 - int((0.0 - min_s) / span * (spark_h - 60))
            if min_s < 0
            else spark_y0 + spark_h - 30
        )

        # Zero line
        draw.line([(spark_x0 + 20, zero_y), (spark_x0 + spark_w - 20, zero_y)], fill=(60, 80, 110), width=1)

        for j, sharpe in enumerate(fold_sharpes):
            bx = spark_x0 + 20 + j * (bar_w + 4)
            norm = (sharpe - min_s) / span
            bar_top = spark_y0 + spark_h - 30 - int(norm * (spark_h - 60))
            color = PASS_COLOR if sharpe >= 0 else FAIL_COLOR
            draw.rectangle([(bx, min(bar_top, zero_y)), (bx + bar_w, max(bar_top, zero_y))], fill=color)
            draw.text((bx, spark_y0 + spark_h - 22), f"{j + 1}", font=font_small, fill=TEXT_SECONDARY)

    # ------------------------------------------------------------------
    # Stats panel (right, below sparkline)
    # ------------------------------------------------------------------
    stats_y = spark_y0 + spark_h + 20
    stats = [
        ("WF XGB Acc", f"{wf_xgb_acc:.1%}"),
        ("WF RF Sharpe", f"{wf_rf_sharpe:+.3f}"),
        ("p-value", f"{wf_xgb.get('p_value', 1.0):.4f}"),
        ("t-stat", f"{wf_xgb.get('t_stat', 0.0):+.3f}"),
    ]
    for k, (lbl, val) in enumerate(stats):
        sx = spark_x0 + 16 + k * 130
        draw.text((sx, stats_y), lbl, font=font_small, fill=TEXT_SECONDARY)
        draw.text((sx, stats_y + 18), val, font=font_label, fill=TEXT_PRIMARY)

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------
    draw.rectangle([(0, HEIGHT - 40), (WIDTH, HEIGHT)], fill=(15, 20, 35))
    draw.text(
        (60, HEIGHT - 28),
        "HOPEFX-AI-TRADING  ·  AGPL-3.0  ·  github.com/HACKLOVE340/HOPEFX-AI-TRADING",
        font=font_small,
        fill=TEXT_SECONDARY,
    )
    draw.text(
        (WIDTH - 200, HEIGHT - 28),
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        font=font_small,
        fill=TEXT_SECONDARY,
    )

    # Gold accent bar at bottom
    draw.rectangle([(0, HEIGHT - 4), (WIDTH, HEIGHT)], fill=ACCENT)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "PNG", optimize=True)
    logger.info(f"Cover written to {output_path}  ({output_path.stat().st_size // 1024} KB)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate assets/cover.png from training reports")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "assets" / "cover.png",
        help="Output path for the cover image (default: assets/cover.png)",
    )
    args = parser.parse_args()
    generate_cover(args.output)


if __name__ == "__main__":
    main()
