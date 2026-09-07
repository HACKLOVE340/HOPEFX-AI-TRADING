# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""CPU, memory, disk and GPU — each measured, or absent with a reason. §22.

The specification lists host telemetry among what the platform already has. It
was not in this repository.

## "I cannot look" is not "there are none"

The GPU report distinguishes them, because they are different facts about the
machine and only one means there is no accelerator. A dashboard that shows
"0 GPUs" when the detection library is missing tells an operator their
inference is running on CPU when it may not be.

## The probe is fetched, not imported at module scope

`_psutil()` and `_nvml()` are functions so a test can replace them, and so an
import failure is a REASON rather than an ImportError at startup.
`infrastructure/health.py` imports psutil at module level, which makes the
whole health surface unimportable on a host without it.
"""

from __future__ import annotations

import logging
from typing import Any

from ai.telemetry.reading import Reading, absent, measured

logger = logging.getLogger(__name__)

_NO_PSUTIL = "psutil is not installed, so this host metric cannot be read at all"
_NO_NVML = "no GPU library is installed (pynvml), so GPUs cannot be detected — this is not the same as having none"


def _psutil() -> Any | None:
    try:
        import psutil

        return psutil
    except ImportError:
        return None


def _nvml() -> Any | None:
    try:
        import pynvml

        pynvml.nvmlInit()
        return pynvml
    except Exception:
        # ImportError, or a driver that is present and refuses to initialise.
        # Both mean the same thing to a caller: it cannot look.
        return None


def _probe(name: str, unit: str, read) -> Reading:
    """Run one probe, turning any failure into a stated absence."""
    lib = _psutil()
    if lib is None:
        return absent(name, _NO_PSUTIL, unit=unit)
    try:
        return measured(name, read(lib), unit=unit)
    except Exception as exc:
        return absent(name, f"the probe failed: {type(exc).__name__}: {exc}", unit=unit)


def cpu() -> Reading:
    return _probe("cpu", "%", lambda p: p.cpu_percent(interval=0.1))


def memory() -> Reading:
    return _probe("memory", "%", lambda p: p.virtual_memory().percent)


def disk() -> Reading:
    return _probe("disk", "%", lambda p: p.disk_usage("/").percent)


def gpu() -> dict[str, Any]:
    """GPU state, with `detectable` separating "cannot look" from "none found"."""
    lib = _nvml()
    if lib is None:
        return {"detectable": False, "devices": [], "reason": _NO_NVML}
    try:
        count = int(lib.nvmlDeviceGetCount())
    except Exception as exc:
        return {"detectable": False, "devices": [], "reason": f"the GPU probe failed: {type(exc).__name__}: {exc}"}

    devices: list[dict[str, Any]] = []
    for index in range(count):
        try:
            handle = lib.nvmlDeviceGetHandleByIndex(index)
            util = lib.nvmlDeviceGetUtilizationRates(handle)
            mem = lib.nvmlDeviceGetMemoryInfo(handle)
            devices.append(
                {
                    "index": index,
                    "utilisation": measured(f"gpu{index}_utilisation", util.gpu, unit="%").as_dict(),
                    "memory": measured(f"gpu{index}_memory", 100.0 * mem.used / mem.total, unit="%").as_dict(),
                }
            )
        except Exception as exc:
            # One unreadable card does not make the others unreadable, and it is
            # listed rather than dropped: a device missing from the list looks
            # like a device that is not there.
            devices.append(
                {
                    "index": index,
                    "utilisation": absent(
                        f"gpu{index}_utilisation", f"{type(exc).__name__}: {exc}", unit="%"
                    ).as_dict(),
                    "memory": absent(f"gpu{index}_memory", f"{type(exc).__name__}: {exc}", unit="%").as_dict(),
                }
            )
    return {"detectable": True, "devices": devices, "reason": ""}


def snapshot() -> dict[str, Any]:
    """Every host reading, and a separate list of what could not be measured."""
    readings = {r.name: r for r in (cpu(), memory(), disk())}
    return {
        "readings": {name: r.as_dict() for name, r in readings.items()},
        "unmeasured": {name: r.reason for name, r in readings.items() if not r.measured},
        "gpu": gpu(),
    }


__all__ = ["cpu", "disk", "gpu", "memory", "snapshot"]
