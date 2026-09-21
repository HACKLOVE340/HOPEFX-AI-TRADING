# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_nginx_and_jwt_alias.py
=======================================
Two defects found by comparing a generated ``.env`` against the environment the
**merged** compose pair actually produces — the configuration production runs
(``-f docker-compose.yml -f deployments/docker-compose.hostinger.yml``), which
nothing had checked before.

**A placeholder that escaped detection.** ``.env.example`` carried::

    JWT_SECRET_KEY=change-me-in-production-min-32-chars

``is_placeholder`` matched only ``CHANGE_ME``, so this different spelling of the
same idea — in the same file, for a JWT signing key — was recognised by neither
the validator nor the generator, and shipped verbatim into every generated
``.env``. It is latent rather than live, because every consumer reads
``SECURITY_JWT_SECRET or JWT_SECRET_KEY`` and the strong value wins. But
``api/auth.py:107`` documents a fallback that differs from ``auth/jwt.py``'s,
which is exactly the arrangement where a token signed by one component is
rejected by another. ``JWT_SECRET_KEY`` is a documented *alias*, so it now
carries the same value rather than a second independent one.

**nginx could not start, for a reason it never said.** The template points
``ssl_certificate`` at ``/etc/letsencrypt/live/${HOPEFX_DOMAIN}/``, and nginx
treats a missing certificate file as a fatal configuration error. On a first
deploy that directory does not exist, so the container died with a message about
a *file* rather than about TLS. Compounding it, the service binds :80 and :443
while a Hostinger VPS already runs traefik on them, and ``depends_on:
service_healthy`` meant it never even attempted to start while the app was
unhealthy — three separate reasons producing one silent ``Created``.

The entrypoint now checks for the certificate before nginx sees the config and
explains both ways out. There is deliberately no HTTP-only mode: an attempt at
one was written and rejected here, because every ``location`` block lives inside
the TLS ``server``, so stripping TLS deletes the proxy with it — measured as
unbalanced braces and ``proxy_pass`` dropping to a single injected line.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_ENTRYPOINT = _ROOT / "nginx/entrypoint.sh"
_TEMPLATE = _ROOT / "nginx/nginx.conf.template"
_ENV_EXAMPLE = (_ROOT / ".env.example").read_text()


def _generated(domain: str = "t.example.com") -> dict[str, str]:
    import importlib.util

    spec = importlib.util.spec_from_file_location("_be", _ROOT / "scripts/bootstrap_env.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    text, _ = module.generate(_ENV_EXAMPLE, domain, keep_comments=False)
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        out[name.strip()] = value.strip()
    return out


# ── The placeholder that was not spelled CHANGE_ME ───────────────────────────


@pytest.mark.parametrize(
    "value",
    ["change-me-in-production-min-32-chars", "CHANGE-ME-x", "changeme123", "Change_Me_please", "  change-me  "],
)
def test_the_other_spellings_are_recognised(value):
    from config.startup_validator import is_placeholder

    assert is_placeholder(value) is True


@pytest.mark.parametrize("value", ["", "a-real-secret", "exchange-rate-key", "unchanged-value", "sk_live_abc"])
def test_real_values_are_still_not_placeholders(value):
    """'exchange' and 'unchanged' contain 'change' — matching must be anchored."""
    from config.startup_validator import is_placeholder

    assert is_placeholder(value) is False


def test_no_generated_value_still_looks_like_a_placeholder():
    """The sweep that found it: any value announcing it should have been replaced."""
    pattern = re.compile(r"change[-_ ]?me|replace[-_ ]?me|your[-_ ]key|placeholder", re.IGNORECASE)
    offenders = {k: v for k, v in _generated().items() if v and pattern.search(v)}
    assert offenders == {}, f"shipped as-is: {offenders}"


def test_the_jwt_alias_carries_the_same_key():
    """A legacy alias for one key, not a second key.

    Consumers read `SECURITY_JWT_SECRET or JWT_SECRET_KEY`; two different values
    means whichever component falls through to the alias signs with a different
    secret than the one that verifies.
    """
    env = _generated()
    assert env["JWT_SECRET_KEY"], "JWT_SECRET_KEY is empty"
    assert env["JWT_SECRET_KEY"] == env["SECURITY_JWT_SECRET"]


def test_the_alias_is_not_left_at_the_template_value():
    assert _generated()["JWT_SECRET_KEY"] != "change-me-in-production-min-32-chars"  # pragma: allowlist secret


# ── nginx says why it cannot start ───────────────────────────────────────────


def test_the_entrypoint_parses():
    result = subprocess.run(["sh", "-n", str(_ENTRYPOINT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_it_checks_for_the_certificate_before_starting_nginx():
    """nginx's own error names a file, not the cause."""
    src = _ENTRYPOINT.read_text()
    assert "fullchain.pem" in src and "privkey.pem" in src
    assert src.index("fullchain.pem") < src.index('exec nginx -g "daemon off;"')


def test_the_message_gives_both_ways_out():
    src = _ENTRYPOINT.read_text()
    assert "certbot" in src, "must say how to obtain a certificate"
    assert "traefik" in src, "must cover the case where another proxy already holds :80/:443"
    assert "compose stop nginx" in src, "must give the command for that case"


def test_the_config_is_validated_before_serving():
    """`nginx -t` fails where the message is visible."""
    assert re.search(r"^nginx -t$", _ENTRYPOINT.read_text(), re.MULTILINE)


def test_the_template_still_requires_a_certificate():
    """If TLS were dropped from the template, the check above would be guarding
    nothing — and the deployment would be serving plaintext."""
    template = _TEMPLATE.read_text()
    assert "ssl_certificate" in template
    assert "listen 443 ssl" in template


def test_every_proxy_location_lives_inside_the_tls_server():
    """The measured reason there is no HTTP-only mode.

    Stripping the `listen 443` server removes every `location ... proxy_pass`
    with it, leaving a config that does not parse. Recorded as a property so a
    future attempt at an HTTP-only mode starts from the constraint rather than
    rediscovering it.
    """
    template = _TEMPLATE.read_text()
    tls_at = template.index("listen 443 ssl")
    before, after = template[:tls_at], template[tls_at:]
    assert "proxy_pass" not in before, "a proxy location exists outside the TLS server — revisit this"
    assert after.count("proxy_pass") >= 3


# ── The generated .env survives a naive Name/Value parser ────────────────────


def _generated_text(**kwargs) -> str:
    import importlib.util

    spec = importlib.util.spec_from_file_location("_be2", _ROOT / "scripts/bootstrap_env.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    text, _ = module.generate(_ENV_EXAMPLE, "t.example.com", **kwargs)
    return text


def test_every_line_splits_into_a_valid_variable_name():
    """A hosting panel splits EVERY line on the first '=', comments included.

    166 of .env.example's comment lines contain one, so a commented .env
    imported into such a panel produced rows like

        NAME '# MetaTrader 5 (required when BROKER_TYPE'  VALUE 'mt5)'
        NAME '#'                                          VALUE '======================'

    each rejected as an invalid variable name — and if the panel writes back
    what it shows, that junk reaches the file the containers read.

    This encodes the panel's parser rather than describing it.
    """
    offenders = [
        line
        for line in _generated_text(keep_comments=False).splitlines()
        if line.strip() and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", line.split("=", 1)[0])
    ]
    assert offenders == [], f"{len(offenders)} lines become junk rows, e.g. {offenders[:3]}"


def test_the_default_output_has_no_comment_lines():
    """`.env.example` is documentation; the generated `.env` is configuration."""
    assert [ln for ln in _generated_text(keep_comments=False).splitlines() if ln.lstrip().startswith("#")] == []


def test_comments_can_still_be_requested_deliberately():
    """--with-comments remains, for a file edited by hand rather than a panel."""
    assert any(ln.lstrip().startswith("#") for ln in _generated_text(keep_comments=True).splitlines())


def test_the_comment_free_output_still_carries_every_variable():
    """Dropping comments must not drop assignments."""
    with_comments = {
        ln.split("=", 1)[0]
        for ln in _generated_text(keep_comments=True).splitlines()
        if "=" in ln and not ln.lstrip().startswith("#")
    }
    without = {ln.split("=", 1)[0] for ln in _generated_text(keep_comments=False).splitlines() if "=" in ln}
    assert with_comments == without, f"lost: {sorted(with_comments - without)[:5]}"


def test_the_documented_command_writes_a_comment_free_file(tmp_path):
    """Exercises the CLI default, not generate()'s parameter.

    The tests above call generate(keep_comments=False) directly, so they pass
    whatever the command-line default is — which is where the behaviour that
    reaches an operator actually lives.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("_be3", _ROOT / "scripts/bootstrap_env.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    out = tmp_path / ".env"
    assert module.main(["--domain", "t.example.com", "--output", str(out)]) == 0

    lines = out.read_text().splitlines()
    assert [ln for ln in lines if ln.lstrip().startswith("#")] == [], "the documented command still emits comments"
    junk = [ln for ln in lines if ln.strip() and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", ln.split("=", 1)[0])]
    assert junk == [], f"lines a panel would reject: {junk[:3]}"


def test_with_comments_is_opt_in_from_the_command_line(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("_be4", _ROOT / "scripts/bootstrap_env.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    out = tmp_path / ".env"
    assert module.main(["--domain", "t.example.com", "--output", str(out), "--with-comments"]) == 0
    assert any(ln.lstrip().startswith("#") for ln in out.read_text().splitlines())
