# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""The `vision` role was declared and structurally unable to do its job.

`ai/gateway/chain.py` configures a vision chain (gemini-3.5-flash →
claude-opus-5). `api/safe_agent_platform.py` accepts `role="vision"` through its
field validator. And `ModelRequest` carried `prompt: str` and nothing else,
while every adapter sent `"content": prompt` — a bare string, not the
content-block array both vendors require for an image.

So an operator could select the vision role and silently get a text model. That
is the third dead control in this subsystem, alongside the audit trail and the
budget ceiling: visible, plausible, and not wired.

The camera end was equally stranded — `VisualIntelligenceWorkspaces.tsx`
captures a frame to a canvas and never reads it, then posts
`{source: 'camera_frame'}` with no image to an endpoint that does not exist.

These tests fail on the pre-fix tree: `ImageRef` does not exist there.
"""

from __future__ import annotations

import base64

import pytest

from ai.gateway.client import GatewayClient, ImageRef, ModelRequest

pytestmark = pytest.mark.unit

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"pretend-pixels").decode()
OTHER_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"different-pixels").decode()


class _Result:
    def __init__(self, text="a candlestick chart"):
        self.text, self.cost_usd, self.tokens_in, self.tokens_out = text, 0.01, 10, 5


class _VisionProvider:
    """Records what it was handed, so the wire shape can be asserted."""

    supports_images = True

    def __init__(self):
        self.calls = []

    def complete(self, *, model, prompt, timeout_s, images=()):
        self.calls.append({"model": model, "prompt": prompt, "images": images})
        return _Result()


class _TextOnlyProvider:
    supports_images = False

    def __init__(self):
        self.calls = []

    def complete(self, *, model, prompt, timeout_s):
        self.calls.append({"model": model, "prompt": prompt})
        return _Result("I cannot see images")


@pytest.fixture(autouse=True)
def _clean():
    from ai.gateway import audit, budget

    budget.reset_for_testing()
    audit.reset_for_testing()
    budget.set_limits(per_operator_usd=100.0, global_usd=1000.0)
    yield
    budget.reset_for_testing()
    audit.reset_for_testing()


def test_a_model_request_can_carry_an_image():
    req = ModelRequest(role="vision", prompt="what is this?", images=(ImageRef(media_type="image/png", data_b64=PNG),))
    assert len(req.images) == 1
    assert req.images[0].media_type == "image/png"


def test_an_image_reaches_the_provider():
    provider = _VisionProvider()
    client = GatewayClient({"google": provider}, cache=None)

    client.call_sync(
        ModelRequest(role="vision", prompt="read this chart", images=(ImageRef("image/png", PNG),)),
        operator="owner",
    )

    assert provider.calls, "the provider was never called"
    assert len(provider.calls[0]["images"]) == 1, "the image did not reach the adapter"


def test_a_leg_that_cannot_see_is_skipped_rather_than_handed_a_blind_prompt():
    """Mirrors how `embed_sync` treats a vendor with no embeddings API.

    Silently dropping the image and asking a text model "what is this?" would
    return a confident answer about nothing at all — far worse than falling
    through to a leg that can actually see.
    """
    blind = _TextOnlyProvider()
    seeing = _VisionProvider()
    client = GatewayClient({"google": blind, "anthropic": seeing}, cache=None)

    client.call_sync(
        ModelRequest(role="vision", prompt="read this chart", images=(ImageRef("image/png", PNG),)),
        operator="owner",
    )

    assert not blind.calls, "a text-only leg was handed an image request"
    assert seeing.calls, "the chain did not fall through to a leg that can see"


def test_a_text_request_still_reaches_a_text_only_provider():
    """The skip must apply only when there is actually an image."""
    blind = _TextOnlyProvider()
    client = GatewayClient({"google": blind}, cache=None)

    client.call_sync(ModelRequest(role="vision", prompt="no image here"), operator="owner")
    assert blind.calls, "a text request was refused by a text-only provider"


def test_two_different_images_with_the_same_prompt_do_not_collide_in_the_cache():
    """The trap this change had to avoid.

    The cache key was prompt + model + tool_state. Two camera frames asked
    "what is this?" would hash identically, and the second would be served the
    FIRST frame's reading — a confident answer about an image nobody looked at.
    """
    from ai.cache.store import ResponseCache

    provider = _VisionProvider()
    client = GatewayClient({"google": provider}, cache=ResponseCache(ttl_s=300))

    common = {"role": "vision", "prompt": "what is this?", "tool_state": "frame"}
    client.call_sync(ModelRequest(**common, images=(ImageRef("image/png", PNG),)), operator="owner")
    client.call_sync(ModelRequest(**common, images=(ImageRef("image/png", OTHER_PNG),)), operator="owner")

    assert len(provider.calls) == 2, "a different image was served a cached answer for another image"


def test_the_same_image_and_prompt_still_caches():
    """The economy has to survive the fix."""
    from ai.cache.store import ResponseCache

    provider = _VisionProvider()
    client = GatewayClient({"google": provider}, cache=ResponseCache(ttl_s=300))

    req = ModelRequest(role="vision", prompt="what is this?", tool_state="frame", images=(ImageRef("image/png", PNG),))
    client.call_sync(req, operator="owner")
    second = client.call_sync(req, operator="owner")

    assert len(provider.calls) == 1, "an identical image+prompt was not served from cache"
    assert second.cached is True


def test_an_image_request_is_still_budgeted_and_audited():
    """Vision must not be a way around the controls every other call passes."""
    from ai.gateway import audit

    provider = _VisionProvider()
    client = GatewayClient({"google": provider}, cache=None)
    client.call_sync(
        ModelRequest(role="vision", prompt="read this", images=(ImageRef("image/png", PNG),)),
        operator="owner",
    )

    records = audit.records()
    assert len(records) == 1
    assert records[0]["role"] == "vision"


def test_an_oversized_image_is_refused_before_it_is_sent():
    """A 4K frame costs real tokens for no extra reading accuracy."""
    from ai.gateway.client import MAX_IMAGE_BYTES

    too_big = base64.b64encode(b"x" * (MAX_IMAGE_BYTES + 1)).decode()
    with pytest.raises(ValueError):
        ModelRequest(role="vision", prompt="p", images=(ImageRef("image/png", too_big),))


def test_an_unsupported_media_type_is_refused():
    with pytest.raises(ValueError):
        ModelRequest(role="vision", prompt="p", images=(ImageRef("application/pdf", PNG),))


# ── wire shape ────────────────────────────────────────────────────────────────


def test_the_anthropic_adapter_builds_a_content_block_array_with_image_first():
    """Both vendors expect the image block BEFORE the text block."""
    from ai.gateway.adapters import AnthropicAdapter

    blocks = AnthropicAdapter._content_blocks("describe it", (ImageRef("image/png", PNG),))
    assert isinstance(blocks, list), "content must be a block array, not a bare string"
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["type"] == "base64"
    assert blocks[0]["source"]["media_type"] == "image/png"
    assert blocks[-1]["type"] == "text"


def test_the_anthropic_adapter_keeps_a_bare_string_when_there_is_no_image():
    """No behaviour change for the text path."""
    from ai.gateway.adapters import AnthropicAdapter

    assert AnthropicAdapter._content_blocks("just text", ()) == "just text"


def test_the_openai_adapter_uses_its_own_image_url_shape():
    """The two vendors differ, and getting one wrong sends a broken request."""
    from ai.gateway.adapters import OpenAIAdapter

    blocks = OpenAIAdapter._content_blocks("describe it", (ImageRef("image/png", PNG),))
    assert isinstance(blocks, list)
    kinds = [b["type"] for b in blocks]
    assert "image_url" in kinds
    image_block = next(b for b in blocks if b["type"] == "image_url")
    assert image_block["image_url"]["url"].startswith("data:image/png;base64,")


def test_vision_capable_adapters_declare_it():
    from ai.gateway.adapters import AnthropicAdapter, GoogleAdapter, OpenAIAdapter

    for adapter in (AnthropicAdapter, OpenAIAdapter, GoogleAdapter):
        assert adapter.supports_images is True, f"{adapter.__name__} does not declare image support"
