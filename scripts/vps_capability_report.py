#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
scripts/vps_capability_report.py — what local model this machine can actually run.

`docs/audit/AI_CORE_SPEC.md` §8 sizes the local model tier by RAM/VRAM and ends
with **"Confirm actual specs first."** Open item 4 is that confirmation. It has
stayed open because the answer requires running something on the VPS, and a
guess in a config file would be worse than no answer: an oversized model does
not degrade, it fails to load or swaps the box to a standstill.

So this reports rather than assumes. Run it on the target machine:

    python scripts/vps_capability_report.py

It prints the measured RAM, VRAM and CPU, and the largest tier the spec's own
table supports on them. Nothing here decides anything — `ai/local_model.py`
reads `LOCAL_MODEL_TIER` from the environment, and this tells you what to set it
to.

The tiers are the spec's, unchanged:

    1B-4B    8 GB RAM
    7B-8B    16 GB RAM / 8 GB VRAM
    13B-14B  24 GB+ VRAM
    30B+     48 GB+ VRAM
    70B+     multi-GPU (80 GB+)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

# The tier table and the probes live in `ai/local_model.py`, which is also what
# the running application uses to decide whether a tier may start. They were
# duplicated here; two copies of a number that gates a model load drift, and the
# drift is invisible until a model fails to load on a live box.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.local_model import (  # after the sys.path bootstrap above
    TIER_ENV,
    best_tier,
    total_ram_gib,
    total_vram_gib,
)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ram, vram = total_ram_gib(), total_vram_gib()
    cpus = os.cpu_count() or 0
    tier = best_tier(ram, vram)

    report = {
        "ram_gib": round(ram, 1),
        "vram_gib": round(vram, 1),
        "cpu_count": cpus,
        "recommended_tier": tier,
        "ollama_present": bool(shutil.which("ollama")),
    }

    if "--json" in argv:
        print(json.dumps(report, indent=2))
        return 0 if tier else 1

    print("HOPEFX local-model capability report\n" + "=" * 46)
    print(f"  RAM        {ram:6.1f} GiB")
    print(f"  VRAM       {vram:6.1f} GiB" + ("  (no NVIDIA GPU detected)" if vram == 0 else ""))
    print(f"  CPUs       {cpus:6d}")
    print(f"  ollama     {'present' if report['ollama_present'] else 'not installed'}")
    print("-" * 46)
    if tier is None:
        print("  No tier fits: under 8 GiB RAM and no GPU.")
        print("  The local tier is not viable here. Use the external API tier only.")
        return 1
    print(f"  Largest viable tier: {tier}")
    print(f"\n  Set this on the target machine:  {TIER_ENV}={tier}")
    if vram == 0:
        print("  CPU inference: expect seconds per response, not milliseconds.")
    print("\n  This measures the machine it runs on. Run it on the VPS, not a laptop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
