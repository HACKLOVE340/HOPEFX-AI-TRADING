# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""News Intelligence — §11's news agent. Read-only.

Headlines, geopolitical risk and sentiment already have machinery behind them:
`data_layer.feeds.news.manager.NewsFeedManager` and the WORDMAP-based
geopolitical scorer that `api/news_feed.py` wires up. What did not exist was an
**agent** — something on the tool bus that can be asked, with a permission tier
and an audit trail, rather than an endpoint a person clicks.

Every handler delegates. A handler that scored a headline itself would be a
second opinion nobody asked for and nobody could audit, and — worse on this
platform — a sentiment number that no feed produced.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def _unavailable(reason: str) -> dict[str, Any]:
    """No answer keys.

    Deliberately carries no `headlines`, no `score` and no `sentiment`: a caller
    that skipped the `available` check must not find something that reads like a
    result.
    """
    return {"available": False, "reason": reason}


def _default_manager() -> Any:
    from api.news_feed import _get_news_manager

    manager = _get_news_manager()
    if manager is None:
        raise RuntimeError("the news feed manager is not constructed in this process")
    return manager


def fetch_headlines(
    *,
    limit: int = 10,
    manager: Callable[[], Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Recent headlines, as the feed manager already has them."""
    try:
        source = (manager or _default_manager)()
        items = source.get_recent(limit=limit) if hasattr(source, "get_recent") else source.latest(limit)
    except Exception as exc:
        logger.info("ai.departments.news: headlines unavailable: %s", exc)
        return _unavailable(str(exc))

    return {
        "available": True,
        "headlines": [
            {
                "title": str(getattr(i, "title", "") or (i.get("title", "") if isinstance(i, dict) else "")),
                "source": str(getattr(i, "source", "") or (i.get("source", "") if isinstance(i, dict) else "")),
                "published_at": str(
                    getattr(i, "published_at", "") or (i.get("published_at", "") if isinstance(i, dict) else "")
                ),
            }
            for i in list(items)[:limit]
        ],
    }


def score_geopolitical_risk(*, text: str = "", scorer: Callable[[], Any] | None = None, **_: Any) -> dict[str, Any]:
    """The geopolitical severity of one piece of text, from the existing scorer."""
    if not text.strip():
        return _unavailable("nothing to score: `text` was empty")
    try:
        from api.news_feed import _get_nuclear_scorer

        engine = (scorer or _get_nuclear_scorer)()
        if engine is None:
            raise RuntimeError("the geopolitical scorer is not available in this process")
        score = engine.score(text) if hasattr(engine, "score") else engine(text)
    except Exception as exc:
        logger.info("ai.departments.news: geopolitical score unavailable: %s", exc)
        return _unavailable(str(exc))
    return {"available": True, "severity": score}


__all__ = ["fetch_headlines", "score_geopolitical_risk"]
