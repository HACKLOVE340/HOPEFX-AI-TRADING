# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""One conversation per user, not one per worker process.

`POST /api/brain/chat` held a module-level `_chat_agent`, built on first use and
reused for every request thereafter. `LLMAgent` keeps a conversation history on
the instance, and nothing about the authenticated caller selected which instance
answered. So every user of a worker shared one history: whatever user A said was
in the prompt sent on behalf of user B, and B's reply could quote it.

That is a confidentiality defect, not a tidiness one — a trader's balances,
positions, strategy and intent are exactly what goes into this box.

These tests call the endpoint function directly with two identities and a stub
backend, and assert on the messages the model was ASKED to complete. Asserting
on the reply would prove less: a model can decline to repeat what it was told,
and the leak has already happened by then.
"""

from __future__ import annotations

import asyncio

import pytest

from api import brain as brain_api
from auth.schemas import TokenPayload


MARKER = "my account number is 9137-SECRET-ALPHA"


class _RecordingAgent:
    """Stands in for LLMAgent: keeps history, and records what it was sent."""

    sent: list[list[dict[str, str]]] = []

    def __init__(self, *_args, **_kwargs) -> None:
        self._history: list[dict[str, str]] = []

    async def chat(self, message: str) -> str:
        self._history.append({"role": "user", "content": message})
        # What the model would be asked to complete, this call.
        type(self).sent.append(list(self._history))
        reply = f"ack:{len(self._history)}"
        self._history.append({"role": "assistant", "content": reply})
        return reply


def _user(sub: str) -> TokenPayload:
    return TokenPayload(sub=sub, role="starter", email=f"{sub}@example.test")


@pytest.fixture(autouse=True)
def _stub_backend(monkeypatch):
    _RecordingAgent.sent = []
    monkeypatch.setattr(brain_api, "_detect_llm_backend", lambda: ("openai", "sk-test"))
    import brain.llm_agent as llm_agent_mod

    monkeypatch.setattr(llm_agent_mod, "LLMAgent", _RecordingAgent)
    brain_api._reset_chat_agents_for_test()
    yield
    brain_api._reset_chat_agents_for_test()


def _say(text: str, sub: str, session: str | None = None):
    req = brain_api.ChatRequest(message=text, session_id=session)
    return asyncio.run(brain_api.chat(req, user=_user(sub)))


def test_one_users_words_never_reach_another_users_prompt():
    _say(MARKER, "user-a")
    _say("what did I just tell you?", "user-b")

    b_prompt = _RecordingAgent.sent[-1]
    assert MARKER not in "".join(m["content"] for m in b_prompt), (
        f"user B's outgoing model request carried user A's message: {b_prompt}"
    )


def test_the_same_session_id_from_two_users_is_two_conversations():
    """A session id is a label the CLIENT chooses, so it cannot be the key.

    Keying on it alone would let anyone read another user's conversation by
    guessing — or simply by both clients defaulting to "default".
    """
    _say(MARKER, "user-a", session="shared")
    _say("what did I just tell you?", "user-b", session="shared")

    b_prompt = _RecordingAgent.sent[-1]
    assert MARKER not in "".join(m["content"] for m in b_prompt)


def test_a_user_keeps_their_own_history_across_requests():
    """The fix must not throw the feature away: the point of the singleton was
    that the conversation continues. It must continue per user."""
    _say("first thing", "user-a")
    _say("second thing", "user-a")

    last = _RecordingAgent.sent[-1]
    assert "first thing" in "".join(m["content"] for m in last)


def test_the_identity_comes_from_the_token_not_the_body():
    """A user field in the request body would let a caller pick a conversation."""
    assert "user" not in brain_api.ChatRequest.model_fields
    assert "user_id" not in brain_api.ChatRequest.model_fields
    assert "sub" not in brain_api.ChatRequest.model_fields


def test_two_requests_on_one_conversation_do_not_interleave(monkeypatch):
    """`LLMAgent.chat` appends the user turn, awaits the model, then appends the
    reply. Two concurrent requests on one conversation interleave those appends
    and leave a history whose turns do not alternate — corruption, not a race
    that resolves itself.

    This drives the ENDPOINT. The first version of this test took the lock
    itself, inside the test body, and therefore still passed with the lock
    deleted from `api/brain.py` — it was proving that `asyncio.Lock` works,
    which was never in doubt. Verified by injection: remove `async with
    convo.lock` from the endpoint and this must fail.

    The stub yields inside the await, so an unserialised endpoint reproduces the
    corruption every run rather than occasionally.
    """

    class _Interleavable:
        instances: list[_Interleavable] = []

        def __init__(self, *_a, **_k):
            self.history: list[str] = []
            type(self).instances.append(self)

        async def chat(self, message: str) -> str:
            self.history.append(f"user:{message}")
            await asyncio.sleep(0)  # the model call
            await asyncio.sleep(0)
            self.history.append(f"assistant:reply-to-{message}")
            return f"reply-to-{message}"

    _Interleavable.instances = []
    import brain.llm_agent as llm_agent_mod

    monkeypatch.setattr(llm_agent_mod, "LLMAgent", _Interleavable)
    brain_api._reset_chat_agents_for_test()

    async def _both():
        req_a = brain_api.ChatRequest(message="first", session_id="s")
        req_b = brain_api.ChatRequest(message="second", session_id="s")
        await asyncio.gather(
            brain_api.chat(req_a, user=_user("user-a")),
            brain_api.chat(req_b, user=_user("user-a")),
        )

    asyncio.run(_both())

    assert len(_Interleavable.instances) == 1, "one conversation must reuse one agent"
    history = _Interleavable.instances[0].history
    roles = [h.split(":")[0] for h in history]
    assert roles == ["user", "assistant", "user", "assistant"], (
        f"turns did not alternate — the history is corrupt: {history}"
    )


def test_retention_is_bounded_and_evicts_the_least_recently_used():
    """An agent per user per session, kept forever, is a memory leak whose key
    the caller controls."""

    async def _run():
        brain_api._reset_chat_agents_for_test()
        cap = brain_api._CHAT_MAX_CONVERSATIONS
        for i in range(cap + 10):
            await brain_api._get_conversation((f"user-{i}", "default"), _RecordingAgent)
        return dict(brain_api._chat_conversations)

    live = asyncio.run(_run())
    assert len(live) <= brain_api._CHAT_MAX_CONVERSATIONS
    # The oldest went; the newest stayed.
    assert ("user-0", "default") not in live
    assert (f"user-{brain_api._CHAT_MAX_CONVERSATIONS + 9}", "default") in live


def test_an_idle_conversation_expires(monkeypatch):
    monkeypatch.setattr(brain_api, "_CHAT_IDLE_EXPIRY_S", 60.0)
    clock = {"t": 1000.0}
    monkeypatch.setattr(brain_api.time, "monotonic", lambda: clock["t"])

    async def _run():
        brain_api._reset_chat_agents_for_test()
        await brain_api._get_conversation(("user-a", "default"), _RecordingAgent)
        clock["t"] += 30
        await brain_api._get_conversation(("user-b", "default"), _RecordingAgent)
        clock["t"] += 40  # user-a now 70s idle, user-b 40s
        await brain_api._get_conversation(("user-c", "default"), _RecordingAgent)
        return set(brain_api._chat_conversations)

    live = asyncio.run(_run())
    assert ("user-a", "default") not in live, "an idle conversation must not be kept"
    assert ("user-b", "default") in live, "a recently used conversation must survive"


def test_evicting_one_conversation_leaves_another_users_history_untouched(monkeypatch):
    """Clearing must reach one conversation and no other.

    The first version of this test popped a key from the registry dict and
    asserted the other key was still there — which tests `dict.pop`, not this
    module. There is no per-user clear endpoint today, so the paths that
    actually remove a conversation are LRU eviction and idle expiry; this drives
    eviction through the endpoint and checks the survivor's HISTORY, not merely
    that its key is present. A conversation that survives eviction with its
    turns lost would pass a presence check and still have lost the user's
    thread.
    """
    monkeypatch.setattr(brain_api, "_CHAT_MAX_CONVERSATIONS", 2)

    _say("b-first", "user-b")
    _say("a-first", "user-a")
    # user-a is now most recent; a third user evicts the least recent (user-b).
    _say("c-first", "user-c")

    live = set(brain_api._chat_conversations)
    assert ("user-b", "default") not in live, "the least recently used was not evicted"
    assert ("user-a", "default") in live

    # user-a's thread continues, with its earlier turn still in the prompt.
    _say("a-second", "user-a")
    a_prompt = "".join(m["content"] for m in _RecordingAgent.sent[-1])
    assert "a-first" in a_prompt, "eviction of another user's conversation disturbed this one"
    assert "b-first" not in a_prompt
    assert "c-first" not in a_prompt


def test_a_token_with_no_subject_is_refused_not_shared():
    """The old code had no identity at all, so "no sub" and "some sub" both got
    the one shared agent. Falling back to a shared conversation is the defect;
    refusing is the only safe answer."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        brain_api._chat_key(TokenPayload(sub="   ", role="starter"), None)
    assert exc.value.status_code == 401


def test_the_endpoint_is_handed_the_authenticated_caller():
    """The isolation is only as good as the identity the endpoint receives.

    Every other test here supplies a TokenPayload directly, which is the right
    level for the history assertions but steps over the question of where that
    payload comes from. If the route's dependency ever returned a shared, a
    default, or a body-supplied identity, those tests would keep passing while
    the leak came straight back.

    So walk the chain: the route's `user` parameter resolves through
    `ai_quota(...)`, and that dependency's own parameter resolves through
    `get_current_user`. Read from the signatures rather than asserted in prose.
    """
    import inspect

    from fastapi.params import Depends as DependsParam

    from api.auth import get_current_user

    param = inspect.signature(brain_api.chat).parameters["user"]
    assert isinstance(param.default, DependsParam), "the route takes `user` without a dependency"

    # `ai_quota(feature=...)` builds the dependency; its own `user` parameter is
    # what decides whose identity arrives.
    inner = inspect.signature(param.default.dependency).parameters["user"]
    assert isinstance(inner.default, DependsParam)
    assert inner.default.dependency is get_current_user, (
        f"the chat route's identity comes from {inner.default.dependency!r}, not from the authenticated user"
    )
