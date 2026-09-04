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
import subprocess
import sys

# (tier name, min RAM GiB, min VRAM GiB — VRAM 0 means CPU inference is viable)
TIERS: tuple[tuple[str, float, float], ...] = (
    ("70B+", 0, 80),
    ("30B+", 0, 48),
    ("13B-14B", 0, 24),
    ("7B-8B", 16, 8),
    ("1B-4B", 8, 0),
)


def total_ram_gib() -> float:
    """Total RAM in GiB, from /proc/meminfo with a sysconf fallback.

    Both failures are reported rather than swallowed: this number decides which
    model tier gets deployed, so silently returning 0.0 would recommend the
    smallest tier on a machine that could run more — a wrong answer dressed as a
    measurement.
    """
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024 * 1024)
    except OSError as exc:
        print(f"  note: /proc/meminfo unreadable ({exc}); trying sysconf", file=sys.stderr)

    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024**3)
    except (ValueError, OSError, AttributeError) as exc:
        print(f"  note: sysconf could not report memory ({exc}); reporting 0", file=sys.stderr)
        return 0.0


def total_vram_gib() -> float:
    """Sum of GPU memory, via nvidia-smi. Absent GPU tooling means 0, not unknown:
    the spec's CPU tier is the honest fallback."""
    if not shutil.which("nvidia-smi"):
        return 0.0
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  note: nvidia-smi failed ({exc}); reporting 0 VRAM", file=sys.stderr)
        return 0.0
    total = 0.0
    for line in out.splitlines():
        try:
            total += float(line.strip()) / 1024
        except ValueError:
            continue
    return total


def best_tier(ram: float, vram: float) -> str | None:
    for name, min_ram, min_vram in TIERS:
        if min_vram and vram >= min_vram:
            return name
        if not min_vram and ram >= min_ram:
            return name
        if min_vram and min_ram and ram >= min_ram and vram >= min_vram:
            return name
    return None


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
    print(f"\n  Set this on the target machine:  LOCAL_MODEL_TIER={tier}")
    if vram == 0:
        print("  CPU inference: expect seconds per response, not milliseconds.")
    print("\n  This measures the machine it runs on. Run it on the VPS, not a laptop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
