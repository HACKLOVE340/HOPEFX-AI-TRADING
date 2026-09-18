# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
Whole-word keyword matching for the news scorers.

Three modules in this package score headlines by looking their keyword
dictionaries up in the article text, and all three did it with a plain
substring test::

    if keyword in text: ...

That matches inside longer words, which on this keyword set is not a rare edge
case — it fires on ordinary English:

===================  ==========  ===================================
Text                 Keyword     Consequence
===================  ==========  ===================================
"wins award"         ``war``     HIGH-impact GEOPOLITICAL, vol x1.3
"software update"    ``war``     same
"went against"       ``gain``    scored *bullish*
"a mission to"       ``miss``    scored bearish
"fallout shelter"    ``fall``    scored bearish
"a couple of"        ``coup``    nuclear-severity keyword match
===================  ==========  ===================================

The naive fix -- requiring a word boundary on both sides -- overcorrects,
because headlines are written in inflected English: "stocks *surges*",
"*gains* on the day", "*falls* sharply", "rate *cuts*". Demanding an exact
word would drop the matches the dictionaries exist to catch.

So a keyword matches when it starts at a word boundary and ends either at a
word boundary or after one common English inflection. "falls" matches "fall";
"fallout" does not.
"""

from __future__ import annotations

import re

__all__ = ["contains_keyword", "count_keyword", "keyword_pattern", "keyword_spans"]

# Suffixes a keyword may pick up and still be the same word. Ordered longest
# first so the alternation prefers the longest match.
_INFLECTIONS = ("ing", "es", "ed", "ly", "s", "d")

_CACHE: dict[str, re.Pattern[str]] = {}


def keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Compile (and cache) the whole-word pattern for one keyword.

    Multi-word keywords ("interest rate") are matched as a phrase whose
    internal spacing is flexible, so a newline or a double space in the source
    text does not hide them.
    """
    cached = _CACHE.get(keyword)
    if cached is not None:
        return cached

    words = keyword.lower().split()
    if not words:
        # An empty keyword must never match; a bare "" pattern matches
        # everywhere and would score every article.
        pattern = re.compile(r"(?!)")
        _CACHE[keyword] = pattern
        return pattern

    body = r"\s+".join(re.escape(word) for word in words)
    suffix = "|".join(_INFLECTIONS)

    # \b only means "word boundary" next to a word character. A keyword that
    # starts or ends in punctuation -- "u.s." is the one that turns up in a
    # hand-edited WORDMAP.json -- would get a \b that can never match, and the
    # keyword would silently never fire. Anchor only the sides that can be.
    lead = r"\b" if words[0][0].isalnum() or words[0][0] == "_" else ""
    # A keyword ending in punctuation admits no inflection and no meaningful
    # trailing boundary, but must still not match mid-word.
    last = words[-1][-1]
    tail = rf"(?:{suffix})?\b" if last.isalnum() or last == "_" else r"(?!\w)"

    pattern = re.compile(rf"{lead}{body}{tail}", re.IGNORECASE)
    _CACHE[keyword] = pattern
    return pattern


def contains_keyword(text: str, keyword: str) -> bool:
    """True when ``keyword`` appears in ``text`` as a whole word."""
    return keyword_pattern(keyword).search(text) is not None


def count_keyword(text: str, keyword: str) -> int:
    """How many times ``keyword`` appears in ``text`` as a whole word."""
    return len(keyword_pattern(keyword).findall(text))


def keyword_spans(text: str, keyword: str) -> list[tuple[int, int]]:
    """Character spans of every whole-word match of ``keyword`` in ``text``.

    ``count_keyword`` answers "how many", which is all two of the three scorers
    need. A caller that has to decide about matches *individually* -- to
    discount the ones used in a non-market sense, say -- needs to know where
    they are, and cannot recover that from a count.
    """
    return [match.span() for match in keyword_pattern(keyword).finditer(text)]
