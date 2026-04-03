# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 HOPEFX
# AGPL-3.0 — modifications shared
"""
update_artifacts.py
===================
Generates assets/cover.png — a 1200×600 social preview image for the repo.

Requires: pip install Pillow

Usage
-----
    python update_artifacts.py              # generate cover.png
    python update_artifacts.py --push       # generate + git commit + push
    python update_artifacts.py --check      # verify Pillow is available, exit 0/1

Called by .github/workflows/update_docs.yml on every push to main.
"""

from __future__ import annotations

import argparse
import subprocess  # nosec B404 - list-form git calls; no shell=True, no user input
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "assets"
OUTPUT_PATH = ASSETS_DIR / "cover.png"

# Production stats for advanced_oos.pkl (3-year held-out OOS, 756 bars).
# Source: ANALYSIS_AND_ROADMAP.md — these are the credible published numbers.
_STATS = {
    "oos_accuracy": "68.0%",
    "backtest_return": "+5.52%",
    "win_rate": "57.8%",
    "max_drawdown": "−0.88%",
    "sharpe": "1.52",
    "profit_factor": "2.28",
}

# ── Palette ───────────────────────────────────────────────────────────────────
_BG_TOP = (8, 12, 24)
_BG_BOT = (14, 24, 46)
_GOLD = (212, 175, 55)
_GOLD_DIM = (140, 110, 30)
_WHITE = (235, 242, 255)
_MUTED = (110, 130, 168)
_GREEN = (52, 199, 128)
_CARD_BG = (16, 26, 52)
_CARD_BORDER = (36, 56, 96)
_PILL_BG = (14, 48, 26)
_SHADOW = (4, 8, 18)


def _gradient(draw, W: int, H: int) -> None:
    for y in range(H):
        t = y / H
        r = int(_BG_TOP[0] + (_BG_BOT[0] - _BG_TOP[0]) * t)
        g = int(_BG_TOP[1] + (_BG_BOT[1] - _BG_TOP[1]) * t)
        b = int(_BG_TOP[2] + (_BG_BOT[2] - _BG_TOP[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))


def _font(size: int, bold: bool = True):
    from PIL import ImageFont

    bold_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    reg_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in bold_paths if bold else reg_paths:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:  # nosec B112 - skip unreadable font file, try next path
                continue
    return ImageFont.load_default()


def generate_cover(output: Path = OUTPUT_PATH) -> Path:
    """Create a 1200×600 PNG and save to *output*. Returns the path."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("ERROR: Pillow not installed. Run: pip install Pillow", file=sys.stderr)
        sys.exit(1)

    W, H = 1200, 600
    img = Image.new("RGB", (W, H), _BG_TOP)
    draw = ImageDraw.Draw(img)

    _gradient(draw, W, H)

    # Left gold accent bar
    draw.rectangle([(0, 0), (5, H)], fill=_GOLD)

    # Subtle vertical grid lines
    for x in range(80, W, 80):
        draw.line([(x, 0), (x, H)], fill=(30, 40, 70), width=1)

    # ── Fonts ─────────────────────────────────────────────────────────────────
    f_logo = _font(82)
    f_tag = _font(25)
    f_sub = _font(15, bold=False)
    f_clabel = _font(15, bold=False)
    f_cval = _font(40)
    f_cnote = _font(12, bold=False)
    f_pill = _font(13)
    f_badge = _font(12, bold=False)
    f_foot = _font(13, bold=False)

    # ── Logo block ────────────────────────────────────────────────────────────
    M = 56  # left margin
    draw.text((M, 48), "HOPEFX", font=f_logo, fill=_GOLD)
    draw.text((M, 146), "AI Gold Trading Platform", font=f_tag, fill=_WHITE)
    draw.text(
        (M, 182),
        "XAUUSD  ·  XGBoost Stacking Ensemble  ·  Prop-Firm Compliant  ·  Paper Mode Live",
        font=f_sub,
        fill=_MUTED,
    )

    # Gold rule
    draw.line([(M, 214), (W - M, 214)], fill=_GOLD_DIM, width=1)

    # ── Stat cards ────────────────────────────────────────────────────────────
    cards = [
        ("OOS Accuracy", _STATS["oos_accuracy"], "p=0.0000 · 756 bars"),
        ("Backtest Return", _STATS["backtest_return"], "48 trades · real GC=F"),
        ("Win Rate", _STATS["win_rate"], f"PF {_STATS['profit_factor']}"),
        ("Max Drawdown", _STATS["max_drawdown"], "3-year held-out OOS"),
        ("Sharpe Ratio", _STATS["sharpe"], "Trade-level · N=48"),
    ]

    n = len(cards)
    gap = 14
    card_w = (W - 2 * M - (n - 1) * gap) // n  # ≈ 196 px
    card_h = 152
    card_y = 232

    for i, (label, value, note) in enumerate(cards):
        cx = M + i * (card_w + gap)

        # Drop shadow
        draw.rounded_rectangle(
            [(cx + 3, card_y + 3), (cx + card_w + 3, card_y + card_h + 3)],
            radius=10,
            fill=_SHADOW,
        )
        # Card body
        draw.rounded_rectangle(
            [(cx, card_y), (cx + card_w, card_y + card_h)],
            radius=10,
            fill=_CARD_BG,
            outline=_CARD_BORDER,
            width=1,
        )
        # Top gold strip
        draw.rounded_rectangle(
            [(cx + 1, card_y + 1), (cx + card_w - 1, card_y + 4)],
            radius=2,
            fill=_GOLD_DIM,
        )

        p = 13  # inner padding
        draw.text((cx + p, card_y + 14), label, font=f_clabel, fill=_MUTED)
        draw.text((cx + p, card_y + 44), value, font=f_cval, fill=_GREEN)
        draw.text((cx + p, card_y + 112), note, font=f_cnote, fill=_MUTED)

    # ── Status pill + badges ──────────────────────────────────────────────────
    pill_y = card_y + card_h + 22

    draw.rounded_rectangle(
        [(M, pill_y), (M + 228, pill_y + 30)],
        radius=15,
        fill=_PILL_BG,
        outline=(28, 96, 48),
        width=1,
    )
    draw.text((M + 14, pill_y + 7), "● PAPER TRADING LIVE", font=f_pill, fill=_GREEN)

    badges = [
        ("Python 3.10–3.12", (28, 48, 96)),
        ("AGPL-3.0", (58, 28, 78)),
        ("3 000+ Tests", (18, 58, 48)),
        ("70% Coverage", (18, 58, 48)),
    ]
    bx = M + 244
    for text, bg in badges:
        # Measure text width via getbbox
        try:
            bbox = draw.textbbox((0, 0), text, font=f_badge)
            tw = bbox[2] - bbox[0]
        except AttributeError:
            tw = len(text) * 7
        bw = tw + 22
        draw.rounded_rectangle(
            [(bx, pill_y), (bx + bw, pill_y + 30)],
            radius=15,
            fill=bg,
            outline=(70, 70, 110),
            width=1,
        )
        draw.text((bx + 11, pill_y + 7), text, font=f_badge, fill=_WHITE)
        bx += bw + 10

    # ── Footer ────────────────────────────────────────────────────────────────
    draw.line([(M, H - 46), (W - M, H - 46)], fill=_CARD_BORDER, width=1)
    draw.text(
        (M, H - 34),
        "github.com/HACKLOVE340/HOPEFX-AI-TRADING  ·  AGPL-3.0  ·  © 2025–2026 HOPEFX",
        font=f_foot,
        fill=_MUTED,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output), "PNG", optimize=True)
    print(f"Cover image saved → {output}")
    return output


def _git_push(output: Path) -> None:
    try:
        subprocess.run(  # nosec B603 B607 - list-form git calls; no shell=True, no user input
            ["git", "add", str(output)], check=True, cwd=ROOT
        )
        r = subprocess.run(  # nosec B603 B607 - list-form git calls; no shell=True, no user input
            ["git", "diff", "--cached", "--quiet"], cwd=ROOT, check=False
        )
        if r.returncode == 0:
            print("No changes to commit — cover.png is already up to date.")
            return
        subprocess.run(  # nosec B603 B607 - list-form git calls; no shell=True, no user input
            ["git", "commit", "-m", "chore: regenerate assets/cover.png"],
            check=True,
            cwd=ROOT,
        )
        subprocess.run(  # nosec B603 B607 - list-form git calls; no shell=True, no user input
            ["git", "push"], check=True, cwd=ROOT
        )
        print("Pushed cover.png to remote.")
    except subprocess.CalledProcessError as exc:
        print(f"Git operation failed: {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate HOPEFX repo cover image.")
    parser.add_argument("--push", action="store_true", help="Commit and push after generating.")
    parser.add_argument("--check", action="store_true", help="Check Pillow is available.")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output path.")
    args = parser.parse_args()

    if args.check:
        try:
            import PIL  # noqa: F401

            print("Pillow is available.")
            sys.exit(0)
        except ImportError:
            print("Pillow is NOT installed. Run: pip install Pillow", file=sys.stderr)
            sys.exit(1)

    generate_cover(Path(args.output))
    if args.push:
        _git_push(Path(args.output))


if __name__ == "__main__":
    main()
