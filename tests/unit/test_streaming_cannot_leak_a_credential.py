# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Streaming must not be a hole in the output guardrail.

`scan_output` screens what a model says before an operator ever sees it. It
works because the whole answer is in hand when it runs. Streaming breaks that
assumption: text goes to the screen as it arrives, so by the time a credential
is complete it has already been rendered, and there is no taking it back.

The mechanism here is release-behind-a-holdback:

* every chunk is appended to a buffer, and the WHOLE buffer is scanned;
* only a prefix of a buffer that scanned clean is ever released;
* a tail is held back so a PARTIAL credential is not released either.

The first rule is what makes it sound. A regex search finds substrings, so a
prefix of a string with no match has no match — releasing only prefixes of
clean buffers cannot release a complete credential.

The holdback is what stops a partial leak, and it has to cover the longest
thing being watched for: the shapes have minimum match lengths in the twenties
and thirties, but `register_known_secret` accepts a value of any length, so a
fixed constant alone would release all but the last 64 characters of a
registered system prompt.

These tests fail on the pre-fix tree — `StreamScanner` does not exist there.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

# A real-shaped Anthropic key. Not a live credential: the prefix is what the
# pattern keys on, and the tail is filler.
FAKE_KEY = "sk-ant-" + "A1b2C3d4E5f6G7h8J9k0" * 2


@pytest.fixture(autouse=True)
def _clean():
    from ai.guardrails import output

    output.reset_known_secrets()
    yield
    output.reset_known_secrets()


def _drain(chunks, scanner):
    """Feed every chunk, returning what was released."""
    out = []
    for c in chunks:
        out.append(scanner.feed(c))
    out.append(scanner.finish())
    return "".join(out)


# ── the property that matters ─────────────────────────────────────────────────


def test_a_credential_split_across_chunks_is_never_released():
    """The whole point. No single chunk contains the key; the buffer does."""
    from ai.guardrails.output import GuardrailViolation, StreamScanner

    scanner = StreamScanner()
    released = ""
    with pytest.raises(GuardrailViolation):
        for i in range(0, len(FAKE_KEY), 3):
            released += scanner.feed(FAKE_KEY[i : i + 3])

    assert FAKE_KEY not in released
    # Not even most of it: the holdback covers the shape's minimum match length.
    assert "sk-ant-" not in released


def test_the_refusal_still_does_not_quote_what_it_found():
    from ai.guardrails.output import GuardrailViolation, StreamScanner

    scanner = StreamScanner()
    with pytest.raises(GuardrailViolation) as exc:
        for ch in FAKE_KEY:
            scanner.feed(ch)

    assert FAKE_KEY not in str(exc.value)
    assert "anthropic api key" in str(exc.value)


def test_a_registered_secret_longer_than_the_constant_holdback_is_not_dribbled_out():
    """A registered value has no shape and no length bound — a system prompt,
    say. A fixed 64-character holdback would release all but its last 64
    characters one chunk at a time, and the scan would only refuse once the
    last character arrived. By then it is on the screen."""
    from ai.guardrails import output
    from ai.guardrails.output import GuardrailViolation, StreamScanner

    # Not a secret — ordinary prose, standing in for one. The pre-commit
    # scanner flags the assignment on its keyword alone, which is the scanner
    # doing its job; this is the documented way to say "deliberate fixture".
    secret = "the system prompt of this deployment, which is long and has spaces " * 4  # pragma: allowlist secret
    output.register_known_secret("system prompt", secret)

    scanner = StreamScanner()
    released = ""
    with pytest.raises(GuardrailViolation):
        for i in range(0, len(secret), 7):
            released += scanner.feed(secret[i : i + 7])

    assert released == "", f"released {len(released)} characters of a registered secret"


# ── it still has to be useful ─────────────────────────────────────────────────


def test_clean_text_comes_out_whole_and_in_order():
    from ai.guardrails.output import StreamScanner

    answer = "Gold is consolidating between 2380 and 2405. " * 20
    scanner = StreamScanner()
    got = _drain([answer[i : i + 11] for i in range(0, len(answer), 11)], scanner)
    assert got == answer


def test_text_is_released_before_the_stream_ends():
    """Otherwise this is buffering with extra steps, and the panel still waits."""
    from ai.guardrails.output import StreamScanner

    scanner = StreamScanner()
    released = "".join(scanner.feed("word " * 40) for _ in range(1))
    assert released, "nothing was released until finish(); the screen gains nothing"


def test_finish_releases_the_held_tail():
    from ai.guardrails.output import StreamScanner

    scanner = StreamScanner()
    early = scanner.feed("a short answer")
    assert early == "", "the holdback should still be covering a short answer"
    assert scanner.finish() == "a short answer"


def test_the_full_text_is_available_for_the_cache_and_the_audit():
    """The gateway caches and audits the whole answer, not the released pieces."""
    from ai.guardrails.output import StreamScanner

    scanner = StreamScanner()
    scanner.feed("half ")
    scanner.feed("and half")
    scanner.finish()
    assert scanner.text == "half and half"


def test_finish_is_idempotent():
    from ai.guardrails.output import StreamScanner

    scanner = StreamScanner()
    scanner.feed("done")
    assert scanner.finish() == "done"
    assert scanner.finish() == ""


def test_an_empty_stream_is_not_an_error():
    from ai.guardrails.output import StreamScanner

    scanner = StreamScanner()
    assert scanner.finish() == ""
    assert scanner.text == ""


def test_scanning_a_long_answer_stays_cheap():
    """Every chunk rescans the whole buffer, which is the correct thing to do
    and worth confirming is not quadratic in a way that matters."""
    import time

    from ai.guardrails.output import StreamScanner

    scanner = StreamScanner()
    chunk = "The regime is range-bound and volume is thin. "
    started = time.monotonic()
    for _ in range(400):
        scanner.feed(chunk)
    scanner.finish()
    elapsed = time.monotonic() - started
    assert len(scanner.text) > 15_000
    assert elapsed < 2.0, f"scanning an 18KB answer took {elapsed:.2f}s"
