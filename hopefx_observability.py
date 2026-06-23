#!/usr/bin/env python3
# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
hopefx_observability.py — make invisible failures visible.

The point of this module is simple: a trading system fails *silently* in a
hundred small `try/except: pass` blocks, and the most important path (a real
broker fill) may never have run. You cannot debug what you cannot see. This
turns "what the code says should happen" into "what actually happened".

Drop this file in the repo root and call ``install()`` once at startup
(top of ``app.py`` / ``run.py``). It writes two artifacts under ``logs/``:

  * ``logs/hopefx_all.log``    — human-readable, every log record from every
                                 logger in the process, plus uncaught/thread/
                                 asyncio exceptions.
  * ``logs/hopefx_events.jsonl`` — one JSON object per line: structured events
                                 (exceptions, manual ``event()`` calls, and
                                 every WARNING+ log record) for grep/jq/replay.

Then replace silent blocks::

    try:
        risky()
    except Exception:
        pass

with::

    from hopefx_observability import observe
    with observe("describe what this block does", fatal=False):
        risky()

Same non-fatal behaviour — but now the failure lands in both log files with a
full traceback instead of vanishing.

To follow ONE trade end-to-end, wrap the entry point in ``trace("order")`` and
every event emitted inside (any thread/coroutine in the same context) is tagged
with the same ``trace`` id.

Stdlib only. Safe to import anywhere. Never raises from logging itself.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

__all__ = ["install", "observe", "event", "trace", "is_installed"]

# ── module state ──────────────────────────────────────────────────────────────
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"installed": False, "events_path": None, "log_dir": None}
_TRACE_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "hopefx_trace_id", default=None
)
_log = logging.getLogger("hopefx.observability")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_installed() -> bool:
    return bool(_STATE["installed"])


# ── structured event sink ───────────────────────────────────────────────────--
def _emit_event(record: dict[str, Any]) -> None:
    """Append one JSON object to hopefx_events.jsonl. Best-effort, thread-safe.

    Never raises — logging must not be able to crash the trading process.
    """
    path = _STATE.get("events_path")
    if not path:
        return
    record.setdefault("ts", _utcnow())
    tid = _TRACE_ID.get()
    if tid and "trace" not in record:
        record["trace"] = tid
    try:
        line = json.dumps(record, default=repr)
    except Exception:  # pragma: no cover — defensive
        line = json.dumps({"ts": _utcnow(), "event": "serialize_error", "repr": repr(record)})
    with _LOCK:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:  # noqa: S110  # nosec B110 — disk full / permissions; logging must never crash
            pass


def event(name: str, **fields: Any) -> None:
    """Record a structured event to both logs (e.g. ``event('order_submitted', id=oid)``)."""
    _emit_event({"event": name, **fields})
    if fields:
        _log.info("event=%s %s", name, " ".join(f"{k}={v!r}" for k, v in fields.items()))
    else:
        _log.info("event=%s", name)


# ── the workhorse: observe() ──────────────────────────────────────────────────
@contextmanager
def observe(label: str, *, fatal: bool = False, **context: Any) -> Iterator[None]:
    """Run a block; on exception, log it to both files instead of swallowing it.

    Drop-in replacement for ``try: ... except Exception: pass``:

      * ``fatal=False`` (default): the exception is logged and **suppressed** —
        identical runtime behaviour to the bare ``pass``, but now visible.
      * ``fatal=True``: the exception is logged and **re-raised**.

    Extra kwargs are attached to the structured event as ``context`` (e.g.
    ``observe("submit order", symbol="XAU_USD", units=100)``).
    """
    start = time.monotonic()
    try:
        yield
    except Exception as exc:
        dur_ms = round((time.monotonic() - start) * 1000, 2)
        tb = traceback.format_exc()
        _emit_event(
            {
                "event": "exception",
                "label": label,
                "fatal": fatal,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "duration_ms": dur_ms,
                "context": context or None,
                "traceback": tb,
            }
        )
        _log.error("OBSERVE FAILED [%s] %s: %s\n%s", label, type(exc).__name__, exc, tb)
        if fatal:
            raise


@contextmanager
def trace(name: str) -> Iterator[str]:
    """Tag every event emitted inside this block (same context) with one id.

    Use it to follow a single trade::

        with trace("xauusd-order"):
            await broker.place_order(...)   # every event() inside is correlated
    """
    tid = f"{name}-{int(time.time() * 1000)}"
    token = _TRACE_ID.set(tid)
    event("trace_start", trace_name=name)
    t0 = time.monotonic()
    try:
        yield tid
    finally:
        event("trace_end", trace_name=name, duration_ms=round((time.monotonic() - t0) * 1000, 2))
        _TRACE_ID.reset(token)


# ── JSONL logging handler (mirrors WARNING+ records into the event stream) ──────
class _JsonlHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            rec: dict[str, Any] = {
                "event": "log",
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                rec["traceback"] = "".join(traceback.format_exception(*record.exc_info))
            _emit_event(rec)
        except Exception:  # noqa: S110  # nosec B110 — never let a log record crash the app
            pass


def _attach_asyncio_handler() -> None:
    """If an event loop is running, route its unhandled exceptions to the logs."""
    try:
        import asyncio

        loop = asyncio.get_running_loop()
    except Exception:
        return  # no running loop yet — caller can re-invoke install() later

    prev = loop.get_exception_handler()

    def _handler(_loop: Any, ctx: dict[str, Any]) -> None:
        exc = ctx.get("exception")
        _emit_event(
            {
                "event": "asyncio_exception",
                "message": ctx.get("message"),
                "error_type": type(exc).__name__ if exc else None,
                "error": str(exc) if exc else None,
                "traceback": "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )
                if exc
                else None,
            }
        )
        _log.error("ASYNCIO UNHANDLED: %s", ctx.get("message"))
        if prev is not None:
            prev(_loop, ctx)
        else:
            _loop.default_exception_handler(ctx)

    loop.set_exception_handler(_handler)


# ── install() ───────────────────────────────────────────────────────────────--
def install(
    log_dir: str | os.PathLike[str] = "logs",
    level: int | None = None,
    capture_warnings: bool = True,
) -> None:
    """Install global observability. Idempotent — safe to call more than once.

    Captures EVERYTHING by default (DEBUG) into ``hopefx_all.log`` so the quiet
    failures — the ``logger.debug(...)`` paths and otherwise-flat code — are no
    longer invisible. Override with ``HOPEFX_OBSERVE_LEVEL`` (e.g. INFO) if the
    DEBUG stream is too verbose. A few pathologically noisy third-party loggers
    (urllib3, asyncio selector, etc.) are capped at INFO unless
    ``HOPEFX_OBSERVE_ALL=1`` is set — then truly everything is captured.

    Sets up the two log files, a root file handler (so every logger is captured),
    a JSONL mirror of WARNING+ records, and process-wide hooks for uncaught
    exceptions on the main thread, worker threads, and the asyncio loop.
    """
    if _STATE["installed"]:
        # On a re-call, just (re)try the asyncio handler — a loop may exist now.
        _attach_asyncio_handler()
        return

    # Resolve capture level: explicit arg > env > DEBUG (capture everything).
    if level is None:
        _lvl_name = os.getenv("HOPEFX_OBSERVE_LEVEL", "DEBUG").upper()
        level = getattr(logging, _lvl_name, logging.DEBUG)

    d = Path(log_dir)
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        d = Path(".")  # fall back to cwd if logs/ can't be created
    all_log = d / "hopefx_all.log"
    _STATE["events_path"] = str(d / "hopefx_events.jsonl")
    _STATE["log_dir"] = str(d)

    root = logging.getLogger()
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)

    # Everything → hopefx_all.log
    if not any(getattr(h, "name", "") == "hopefx_all" for h in root.handlers):
        fh = logging.FileHandler(all_log, encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        fh.set_name("hopefx_all")
        root.addHandler(fh)

    # WARNING+ → hopefx_events.jsonl
    if not any(getattr(h, "name", "") == "hopefx_jsonl" for h in root.handlers):
        jh = _JsonlHandler()
        jh.setLevel(logging.WARNING)
        jh.set_name("hopefx_jsonl")
        root.addHandler(jh)

    # Uncaught exceptions on the main thread.
    _prev_excepthook = sys.excepthook

    def _excepthook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        _emit_event(
            {
                "event": "uncaught_exception",
                "error_type": exc_type.__name__,
                "error": str(exc),
                "traceback": "".join(traceback.format_exception(exc_type, exc, tb)),
            }
        )
        _log.critical("UNCAUGHT %s: %s", exc_type.__name__, exc)
        _prev_excepthook(exc_type, exc, tb)

    sys.excepthook = _excepthook

    # Uncaught exceptions in worker threads.
    if hasattr(threading, "excepthook"):
        def _threadhook(args: Any) -> None:
            _emit_event(
                {
                    "event": "thread_exception",
                    "thread": getattr(args.thread, "name", "?"),
                    "error_type": args.exc_type.__name__,
                    "error": str(args.exc_value),
                    "traceback": "".join(
                        traceback.format_exception(
                            args.exc_type, args.exc_value, args.exc_traceback
                        )
                    ),
                }
            )
            _log.error("THREAD UNCAUGHT [%s] %s", getattr(args.thread, "name", "?"), args.exc_type.__name__)

        threading.excepthook = _threadhook

    if capture_warnings:
        logging.captureWarnings(True)

    # Unraisable exceptions — failures in __del__, GC finalizers, weakref
    # callbacks. These are the most "flat" of all: Python prints them to stderr
    # and moves on. Route them into the event stream.
    if hasattr(sys, "unraisablehook"):
        _prev_unraisable = sys.unraisablehook

        def _unraisablehook(args: Any) -> None:
            exc = args.exc_value
            _emit_event(
                {
                    "event": "unraisable_exception",
                    "error_type": type(exc).__name__ if exc else None,
                    "error": str(exc) if exc else None,
                    "object": repr(getattr(args, "object", None)),
                    "traceback": "".join(
                        traceback.format_exception(args.exc_type, exc, args.exc_traceback)
                    )
                    if exc
                    else None,
                }
            )
            _log.error("UNRAISABLE %s", type(exc).__name__ if exc else "?")
            _prev_unraisable(args)

        sys.unraisablehook = _unraisablehook

    # Cap a few pathologically chatty third-party loggers so the DEBUG stream
    # stays readable — unless HOPEFX_OBSERVE_ALL=1 ("capture literally all").
    if os.getenv("HOPEFX_OBSERVE_ALL", "").lower() not in ("1", "true", "yes"):
        for _noisy in ("urllib3", "asyncio", "websockets", "aiohttp.access", "charset_normalizer", "PIL"):
            logging.getLogger(_noisy).setLevel(logging.INFO)

    _attach_asyncio_handler()
    _STATE["installed"] = True
    event(
        "observability_installed",
        all_log=str(all_log),
        events=_STATE["events_path"],
        capture_level=logging.getLevelName(level),
        pid=os.getpid(),
    )
    _log.info(
        "hopefx observability installed (capture=%s) → %s / %s",
        logging.getLevelName(level),
        all_log,
        _STATE["events_path"],
    )


if __name__ == "__main__":  # tiny self-test
    install()
    event("self_test_event", note="hello")
    with observe("self_test_block_that_fails"):
        raise ValueError("boom (expected)")
    with trace("self_test_trace"):
        event("inside_trace")
    print(f"OK — wrote {_STATE['log_dir']}/hopefx_all.log and hopefx_events.jsonl")
