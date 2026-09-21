#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Make impossible OHLC bars possible, and write down every edit.

    python scripts/clamp_ohlc.py data/XAUUSD_40Y.csv

Produces `<name>_clamped.csv` beside the source, plus
`<name>_clamped.provenance.json` recording the source's sha256 and every bar
that changed, with its before and after.

## What this is, and what it is not

`data/XAUUSD_40Y.csv` carries 441 bars whose OHLC cannot have happened: high
below low, high below the open/close body, or low above it. §E15 measured them
and left them alone, because rewriting a price is inventing one. The owner then
chose to clamp with recorded provenance and default training to the clean 2020+
window.

The rule is the smallest edit that makes a bar possible:

    high := max(high, open, close)
    low  := min(low,  open, close)

Open and close are never touched — those are prints, and the extremes are the
fields that contradict them. A clamped high is still a **reconstruction**: it is
the lowest high consistent with the body, not what the market reached. That is
why nothing here overwrites the source, why every edit is written down, and why
`ml/cached_series.py` reports a repaired series as repaired.

Bars that already satisfy the rule are byte-identical in the output. A repair
that moves a bar nobody complained about is a second, unrecorded fabrication.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

RULE = "high := max(high, open, close); low := min(low, open, close); open and close unchanged"

_COLUMNS = ["open", "high", "low", "close", "volume"]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    if "date" not in frame.columns:
        raise ValueError(f"{path.name}: no date column (found {list(frame.columns)})")
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    frame = frame.set_index("date").sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    return frame[[c for c in _COLUMNS if c in frame.columns]].astype(float)


def clamp_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Return (clamped frame, edits). Pure — the input is not modified."""
    out = frame.copy()
    body_hi = out[["open", "close"]].max(axis=1)
    body_lo = out[["open", "close"]].min(axis=1)

    new_high = out[["high"]].join(body_hi.rename("b")).max(axis=1)
    new_low = out[["low"]].join(body_lo.rename("b")).min(axis=1)

    changed = (new_high != out["high"]) | (new_low != out["low"])
    edits: list[dict] = []
    for stamp in out.index[changed]:
        edits.append(
            {
                "date": stamp.date().isoformat(),
                "before": {"high": float(out.at[stamp, "high"]), "low": float(out.at[stamp, "low"])},
                "after": {"high": float(new_high[stamp]), "low": float(new_low[stamp])},
            }
        )
    out["high"] = new_high
    out["low"] = new_low
    return out, edits


def clamp_file(source: Path, destination: Path | None = None) -> tuple[Path, Path]:
    """Clamp *source* into *destination*, writing a provenance sidecar.

    Returns (csv_path, provenance_path). The source is never modified.
    """
    source = Path(source)
    if destination is None:
        destination = source.with_name(f"{source.stem}_clamped.csv")
    destination = Path(destination)

    frame = _load(source)
    clamped, edits = clamp_frame(frame)

    destination.parent.mkdir(parents=True, exist_ok=True)
    clamped.to_csv(destination, index_label="date")

    provenance = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "tool": "scripts/clamp_ohlc.py",
        "rule": RULE,
        "note": (
            "Clamped highs and lows are reconstructions, not observed prices. "
            "The smallest edit that makes each bar possible was applied; open and "
            "close are untouched. Prefer the clean window recorded in "
            "ml/cached_series.CLEAN_SINCE for training."
        ),
        "source": {"name": source.name, "sha256": _sha256(source)},
        "bars_total": int(len(frame)),
        "bars_edited": len(edits),
        "edits": edits,
    }
    prov_path = destination.with_name(f"{destination.stem}.provenance.json")
    prov_path.write_text(json.dumps(provenance, indent=2) + "\n")
    return destination, prov_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="CSV to repair, e.g. data/XAUUSD_40Y.csv")
    ap.add_argument("-o", "--out", default=None, help="output CSV (default: <name>_clamped.csv)")
    args = ap.parse_args(argv)

    source = Path(args.source)
    if not source.exists():
        print(f"error: {source} does not exist", file=sys.stderr)
        return 2

    csv_path, prov_path = clamp_file(source, Path(args.out) if args.out else None)
    prov = json.loads(prov_path.read_text())
    print(f"source     {source}  (sha256 {prov['source']['sha256'][:12]}…)")
    print(f"bars       {prov['bars_total']}")
    print(f"edited     {prov['bars_edited']}  ({100.0 * prov['bars_edited'] / max(prov['bars_total'], 1):.1f}%)")
    print(f"rule       {RULE}")
    print(f"wrote      {csv_path}")
    print(f"provenance {prov_path}")
    if prov["edits"]:
        first, last = prov["edits"][0], prov["edits"][-1]
        print(f"range      {first['date']} → {last['date']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
