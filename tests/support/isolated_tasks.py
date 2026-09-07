# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Probe tasks that run in a REAL child process, for §24's isolation tests.

They live in an importable module rather than inside the test file because
that is the whole point of a task contract: an isolated task is named by a
dotted reference the child can import, not a closure the parent happens to
hold. A test that could pass with a lambda would be testing something this
design deliberately refuses.
"""

from __future__ import annotations

import os
import time
from typing import Any

#: Not a function. Pointed at by the test that proves a contract refuses a
#: name that resolves and cannot be called.
NOT_A_FUNCTION = "a string is not a task"


def succeed(*, value: str = "done", report: Any = None) -> str:
    if report is not None:
        report("starting")
        report("half way")
    return value


def report_pid(*, report: Any = None) -> int:
    """The child's own process id, so the parent can prove they differ."""
    return os.getpid()


def raise_error(*, report: Any = None) -> None:
    raise ValueError("this task was always going to fail")


def die_hard(*, report: Any = None) -> None:
    """Leave without unwinding, the way a segfaulting native extension does.

    `os._exit` skips every finally block and every atexit hook, so the parent
    sees a dead process and no result — which is exactly the case a thread pool
    cannot survive and a process boundary can.
    """
    os._exit(9)


def spin_forever(*, report: Any = None) -> None:
    if report is not None:
        report("spinning")
    while True:
        time.sleep(0.05)


def eat_memory(*, megabytes: int = 4096, report: Any = None) -> int:
    """Allocate far past any sane cap, so the limit is what stops it."""
    blocks = []
    for _ in range(megabytes):
        blocks.append(bytearray(1024 * 1024))
    return len(blocks)


def echo_operator(*, operator: str = "", report: Any = None) -> str:
    return operator
