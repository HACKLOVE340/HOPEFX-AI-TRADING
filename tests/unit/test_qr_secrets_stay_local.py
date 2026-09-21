# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_qr_secrets_stay_local.py
=========================================
Regression tests for finding S-01: confidential values were being handed to a
third-party QR image service.

Two places did it.

``api/two_factor.py`` built, and returned to the client::

    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={uri}"

where ``uri`` is the otpauth URI — which **is** the TOTP shared secret, next to
the user identifier, and was not even URL-encoded. Any client rendering that
field ships the second factor to someone else's request log. The web UI had
already been moved to local encoding (``frontend/src/components/QRCode.tsx``),
but the field stayed in ``SetupResponse`` and therefore in the OpenAPI schema,
so every other consumer — the mobile app, an integrator, anyone reading the
docs — was still being handed the leaking URL.

``dashboard/src/pages/CryptoCheckout.tsx`` did the same for a crypto **deposit
address**, on a comment reading "in production use a real QR library". That is
the production bundle: ``dashboard/dist/`` is committed and mounted at
``/godmode/``. Whoever serves the image chooses the address the customer's
wallet actually scans, while the address text rendered underneath still reads
correctly — so "check the address" does not catch the swap.

What is deliberately *not* a finding: ``api/mobile.py`` uses the same service
for the App Store and Play Store QR codes. Those encode public URLs. The
distinction is confidentiality of the encoded value, not the service, and
``_qr_url``'s own docstring already draws it — these tests pin that line rather
than banning the host outright.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QR_HOST = "api.qrserver.com"


def _source_without_docstring(obj) -> str:
    """Function source with its docstring removed.

    The docstrings above and in the modules under test *describe* the old
    URL, so a plain substring search over the source would match the
    explanation of the bug rather than the bug.
    """
    src = inspect.getsource(obj)
    tree = ast.parse(inspect.cleandoc(src))
    node = tree.body[0]
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return "\n".join(ast.unparse(stmt) for stmt in body)


@pytest.mark.unit
class TestTwoFactorSetupResponse:
    def test_setup_response_has_no_qr_url_field(self):
        from api.two_factor import SetupResponse

        assert "qr_url" not in SetupResponse.model_fields, (
            "SetupResponse must not carry a third-party QR image URL: its query "
            "string contained the otpauth URI, i.e. the TOTP shared secret (S-01)."
        )

    def test_setup_response_still_returns_what_a_client_needs(self):
        from api.two_factor import SetupResponse

        assert {"secret", "otpauth_uri"} <= set(SetupResponse.model_fields), (
            "Removing qr_url must not remove the client's ability to enrol — it encodes otpauth_uri itself."
        )

    def test_setup_endpoint_does_not_build_a_third_party_url(self):
        from api.two_factor import setup_2fa

        body = _source_without_docstring(setup_2fa)
        assert _QR_HOST not in body, (
            f"setup_2fa still constructs a {_QR_HOST} URL. The otpauth URI is the "
            "shared secret; it must never leave the browser (S-01)."
        )

    @pytest.mark.asyncio
    async def test_response_payload_carries_no_external_url(self):
        """End to end over the real endpoint, not just its signature."""
        from api.two_factor import setup_2fa

        class _User:
            sub = "qr-regression-user"

        response = await setup_2fa(user=_User())
        payload = response.model_dump()

        assert _QR_HOST not in str(payload)
        assert payload["otpauth_uri"].startswith("otpauth://totp/")
        assert payload["secret"] in payload["otpauth_uri"]


@pytest.mark.unit
class TestMobileStoreQrIsStillAllowed:
    """The public-URL case stays — banning the host outright would be wrong."""

    def test_app_store_qr_still_uses_the_service(self):
        from api.mobile import _APP_STORE_URL, _qr_url

        url = _qr_url(_APP_STORE_URL)
        assert url.startswith(f"https://{_QR_HOST}/")

    def test_public_url_is_percent_encoded_in_the_query_string(self):
        from api.mobile import _qr_url

        url = _qr_url("https://example.com/a?b=c&d=e")
        assert "data=https%3A%2F%2Fexample.com" in url, (
            "The encoded value must be percent-encoded so it cannot inject "
            "further query parameters into the image request."
        )


@pytest.mark.unit
class TestDashboardCheckoutEncodesLocally:
    """`dashboard/dist/` is committed and served, so the source matters here."""

    _CHECKOUT = _REPO_ROOT / "dashboard" / "src" / "pages" / "CryptoCheckout.tsx"

    def test_checkout_source_exists(self):
        assert self._CHECKOUT.is_file()

    def test_deposit_address_qr_is_not_fetched_from_a_third_party(self):
        source = self._CHECKOUT.read_text(encoding="utf-8")
        assert _QR_HOST not in source, (
            "The crypto deposit address QR must be encoded in-browser. Serving "
            "it from a third party lets whoever controls that response redirect "
            "the customer's funds while the printed address still looks right."
        )

    def test_checkout_uses_the_local_component(self):
        source = self._CHECKOUT.read_text(encoding="utf-8")
        assert "from '../components/QRCode'" in source
        assert "<QRCode" in source

    def test_local_component_is_present_and_uses_the_qrcode_package(self):
        component = _REPO_ROOT / "dashboard" / "src" / "components" / "QRCode.tsx"
        assert component.is_file()
        assert "from 'qrcode'" in component.read_text(encoding="utf-8")

    def test_qrcode_is_a_declared_dashboard_dependency(self):
        import json

        manifest = json.loads((_REPO_ROOT / "dashboard" / "package.json").read_text(encoding="utf-8"))
        assert "qrcode" in manifest["dependencies"], (
            "The component imports `qrcode`; without the declared dependency the dashboard build breaks."
        )
