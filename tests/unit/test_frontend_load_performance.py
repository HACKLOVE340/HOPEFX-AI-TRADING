# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_frontend_load_performance.py
============================================
Two reasons the SPA loaded slowly, neither of which was visible in the code.

**Nothing compressed the JavaScript.** The build ships ~2.8 MB across its
chunks, the largest single one 415 kB. Starlette's `StaticFiles` does not gzip,
the app registered no compression middleware, and docker-compose publishes the
app on `8000:8000` — so hitting the host directly bypasses nginx entirely and
gets raw bytes. Even through nginx it would not have helped: `gzip_types`
listed `application/javascript` but not `text/javascript`, which is what
nginx's own mime.types has mapped `.js` to since 1.21.1, so every chunk fell
outside the type list.

**Nothing set Cache-Control.** Vite emits content-hashed filenames, so a file
at a given URL is immutable by construction. Without a cache header the browser
revalidated all ~15 assets on every navigation — a full round trip each, before
anything could paint. On a distant VPS that is most of the perceived load time
even when every response comes back 304.

The pairing matters: `index.html` must go the other way. It is the document
naming the current hashed bundles, so caching it pins the browser to a stale
build after a deploy, pointing at assets that may no longer exist.
"""

from __future__ import annotations


import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


# ── Compression ───────────────────────────────────────────────────────────────


@pytest.fixture
def compressed_app():
    from core.middleware import setup_compression

    app = FastAPI()
    big = "console.log(1);" * 20_000

    @app.get("/big.js")
    def _big():
        return PlainTextResponse(big, media_type="text/javascript")

    @app.get("/tiny")
    def _tiny():
        return PlainTextResponse("ok")

    setup_compression(app)
    return app, big


def test_a_large_javascript_chunk_is_compressed(compressed_app):
    app, big = compressed_app
    client = TestClient(app)

    r = client.get("/big.js", headers={"Accept-Encoding": "gzip"})

    assert r.headers["content-encoding"] == "gzip"
    # httpx decodes transparently, so r.content is the *decompressed* body —
    # the wire size has to come from the header.
    wire_bytes = int(r.headers["content-length"])
    assert wire_bytes < len(big) / 10, f"compression barely reduced the payload: {wire_bytes} of {len(big)}"
    assert r.text == big, "the body did not survive the round trip"


def test_a_small_response_is_not_compressed(compressed_app):
    """Below the floor the round trip costs more than it saves."""
    app, _ = compressed_app

    r = TestClient(app).get("/tiny", headers={"Accept-Encoding": "gzip"})

    assert r.headers.get("content-encoding") is None


def test_a_client_that_cannot_decompress_gets_plain_bytes(compressed_app):
    """Respecting Accept-Encoding is the whole contract."""
    app, big = compressed_app

    r = TestClient(app).get("/big.js", headers={"Accept-Encoding": "identity"})

    assert r.headers.get("content-encoding") is None
    assert r.text == big


def test_compression_is_registered_in_the_middleware_stack():
    """A helper nobody calls is not a fix."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "core" / "middleware.py").read_text(encoding="utf-8")

    assert "setup_compression(app)" in src, "setup_compression is never called from register_all"


# ── Cache policy ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "assets/app-analytics-DUbayt-I.js",
        "assets/index-BOwIQe82.js",
        "assets/index-ClqWLFI1.css",
        "assets/vendor-react-EndrQkTQ.js",
    ],
)
def test_content_hashed_assets_are_cached_immutably(path):
    """The hash changes when the bytes change, so the URL never needs revalidating."""
    from core.page_routes import _asset_cache_headers

    cc = _asset_cache_headers(path)["Cache-Control"]

    assert "immutable" in cc
    assert "max-age=31536000" in cc


def test_index_html_is_never_cached():
    """It names the current bundles; a cached copy pins the browser to a stale build."""
    from core.page_routes import _asset_cache_headers

    cc = _asset_cache_headers("index.html")["Cache-Control"]

    assert "no-store" in cc
    assert "immutable" not in cc


@pytest.mark.parametrize("path", ["favicon.ico", "manifest.json", "robots.txt", "logo.png"])
def test_unhashed_files_are_revalidated(path):
    """Their URL is stable across deploys, so a change is invisible without a check."""
    from core.page_routes import _asset_cache_headers

    cc = _asset_cache_headers(path)["Cache-Control"]

    assert "must-revalidate" in cc
    assert "immutable" not in cc


def test_a_nested_index_html_is_still_not_cached():
    """Matching on the basename, not the full path."""
    from core.page_routes import _asset_cache_headers

    assert "no-store" in _asset_cache_headers("some/nested/index.html")["Cache-Control"]


def test_the_hash_check_is_linear_on_a_hostile_path():
    """The first version of this was a regex, and it was quadratic.

    `.+-[A-Za-z0-9_-]{8,}\\.[A-Za-z0-9]+$` looks reasonable, but `.+` and the
    character class can both match '-', so a non-matching input has to be split
    between them every possible way. Measured on "-a" repeated: 4 k chars 10 ms,
    8 k 39 ms, 16 k 163 ms — quadratic, and reachable because
    `_CachingStaticFiles` passes the raw request path with no length bound.
    CodeQL caught it (alert 24773). Replaced with a single-pass scan.
    """
    import time

    from core.page_routes import _asset_cache_headers

    hostile = "-a" * 100_000

    t0 = time.perf_counter()
    _asset_cache_headers(hostile)
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.05, f"hash detection took {elapsed:.3f}s on a 200 kB path — still backtracking"


@pytest.mark.parametrize(
    ("name", "hashed"),
    [
        ("app-analytics-DUbayt-I.js", True),  # hash contains a '-'
        ("index-BOwIQe82.js", True),
        ("vendor-react-EndrQkTQ.js", True),
        ("style-a_b-c_d1.css", True),  # hash contains '_'
        ("favicon.ico", False),
        ("manifest.json", False),
        ("app-short.js", False),  # suffix too short to be a hash
        ("noextension", False),
        ("trailing.", False),
        ("-BOwIQe82.js", False),  # no name before the separator
        ("", False),
    ],
)
def test_content_hash_detection_boundaries(name, hashed):
    from core.page_routes import _has_content_hash

    assert _has_content_hash(name) is hashed


# ── nginx configuration ───────────────────────────────────────────────────────


@pytest.mark.parametrize("conf", ["nginx/nginx.conf", "nginx/nginx.conf.template"])
def test_nginx_compresses_the_mime_type_js_is_actually_served_as(conf):
    """`text/javascript`, not just `application/javascript` — see the module docstring."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / conf).read_text(encoding="utf-8")

    assert "gzip on;" in src
    assert "text/javascript" in src, f"{conf} would leave every SPA chunk uncompressed"
