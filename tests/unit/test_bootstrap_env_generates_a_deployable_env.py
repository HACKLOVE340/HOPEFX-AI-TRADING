# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_bootstrap_env_generates_a_deployable_env.py
============================================================
A fresh production install could not start, and the reason was that nothing
generated a production ``.env``.

``scripts/bootstrap_dev.py`` writes a complete development ``.env`` with real
random secrets. Production had no equivalent — the starting point was
``.env.example``, which ships fourteen ``CHANGE_ME_*`` placeholders to be
replaced by hand. Miss one and nothing says so at the point of the mistake; the
deploy reports::

    dependency failed to start: container hopefx-ai-trading-app-1 is unhealthy

which is what ``sys.exit(1)`` inside startup validation looks like from outside
the container.

``scripts/bootstrap_env.py`` closes that gap. The tests that matter here are not
"no CHANGE_ME remains" — that is the easy half. They are the three relationships
between placeholders that hand-editing and any per-line generator get wrong, each
of which fails *after* a successful-looking deploy:

* ``CHANGE_ME_db_password`` occurs three times — ``POSTGRES_PASSWORD``,
  ``DB_PASSWORD``, and embedded inside ``DATABASE_URL``. Generate them
  independently and Postgres comes up with one password while the app connects
  with another.
* ``CHANGE_ME_redis_password`` occurs twice, once inside ``REDIS_URL``.
* ``CHANGE_ME_generate_64_char_hex_secret`` is shared by ``SECURITY_JWT_SECRET``
  and ``CRYPTO_WEBHOOK_SECRET``, which must **not** match. Substituting by
  placeholder token — the obvious implementation — makes them equal, so
  recovering either secret yields the other.

The end-to-end test runs the real ``.env.example`` through the real
``validate_environment(strict=True)``. That is the check the container actually
performs, so it is the one worth asserting.
"""

from __future__ import annotations

import base64
import importlib.util
import pathlib
import re

import pytest

pytestmark = pytest.mark.unit

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_TEMPLATE = (_ROOT / ".env.example").read_text()
_DOMAIN = "hopefx.example.com"


def _module():
    spec = importlib.util.spec_from_file_location("_bootstrap_env", _ROOT / "scripts/bootstrap_env.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _parse(text: str) -> dict[str, str]:
    """Parse the way docker compose does — including the part that surprises.

    Compose strips an inline comment only when the value is NON-empty. When the
    value is empty it takes the whole comment as the value:

        FOO=          # a comment   ->  FOO='# a comment'
        BAR=value     # a comment   ->  BAR='value'

    Verified against a real `docker compose config`. This helper originally
    stripped ` #...` unconditionally, which is more forgiving than compose and
    hid the very defect these tests exist to catch — the generated env reached
    the container with 33 variables holding their own descriptions.
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, raw = stripped.partition("=")
        body = raw.strip()
        value = body if body.startswith("#") else re.sub(r"\s+#.*$", "", raw).strip()
        out[name.strip()] = value
    return out


@pytest.fixture(scope="module")
def generated() -> dict[str, str]:
    text, _ = _module().generate(_TEMPLATE, _DOMAIN)
    return _parse(text)


# ── The property that actually gates a deploy ────────────────────────────────


def test_the_generated_env_passes_production_startup_validation(monkeypatch, generated):
    """The real validator, in production mode, over the real template.

    This is the check the container runs before reporting itself healthy.
    """
    from config.startup_validator import StartupValidationError, validate_environment

    for key in list(generated):
        monkeypatch.delenv(key, raising=False)
    for key, value in generated.items():
        monkeypatch.setenv(key, value)

    try:
        validate_environment(strict=True)
    except StartupValidationError as exc:
        pytest.fail(f"generated .env does not start in production:\n{exc}")


def test_nothing_is_left_unreplaced(generated):
    leftovers = {k: v for k, v in generated.items() if "CHANGE_ME" in v}
    assert leftovers == {}


def test_the_domain_reaches_every_variable_that_needs_it(generated):
    assert "YOUR_DOMAIN" not in "\n".join(generated.values())
    assert generated["APP_BASE_URL"] == f"https://{_DOMAIN}"
    assert generated["HOPEFX_DOMAIN"] == _DOMAIN
    assert generated["ALLOWED_ORIGINS"] == f"https://{_DOMAIN},https://www.{_DOMAIN}"


# ── The relationships between placeholders ───────────────────────────────────


def test_the_database_password_is_the_same_in_all_three_places(generated):
    """Independent values here produce a Postgres the app cannot log in to —
    after the deploy reports success."""
    embedded = re.search(r"postgresql(?:\+\w+)?://[^:]+:([^@]+)@", generated["DATABASE_URL"])
    assert embedded, f"could not read the password out of {generated['DATABASE_URL']!r}"
    assert embedded.group(1) == generated["POSTGRES_PASSWORD"] == generated["DB_PASSWORD"]


def test_the_redis_password_is_the_same_in_both_places(generated):
    embedded = re.search(r"redis://:([^@]+)@", generated["REDIS_URL"])
    assert embedded
    assert embedded.group(1) == generated["REDIS_PASSWORD"]


def test_secrets_sharing_a_placeholder_token_do_not_share_a_value(generated):
    """SECURITY_JWT_SECRET and CRYPTO_WEBHOOK_SECRET both read
    CHANGE_ME_generate_64_char_hex_secret in the template. Substituting by token
    would make them equal."""
    assert generated["SECURITY_JWT_SECRET"] != generated["CRYPTO_WEBHOOK_SECRET"]


def test_every_generated_secret_is_distinct_except_the_declared_alias(generated):
    module = _module()
    names = set(module._GENERATORS) | set(module._ALIASES)
    values = [generated[n] for n in sorted(names) if generated.get(n)]
    duplicates = len(values) - len(set(values))
    assert duplicates == len(module._ALIASES), "an undeclared pair of secrets shares a value"


# ── Values the consumers can actually use ────────────────────────────────────


def test_the_encryption_key_decodes_to_an_aes256_key(generated, monkeypatch):
    """database/encryption.py disables field encryption and falls back to
    plaintext when this does not decode to exactly 32 bytes — it logs an error
    and carries on, so a wrong value looks like a working deploy."""
    monkeypatch.setenv("DB_ENCRYPTION_KEY", generated["DB_ENCRYPTION_KEY"])
    from database.encryption import _load_key

    key = _load_key()
    assert key is not None, "generated DB_ENCRYPTION_KEY silently disables encryption"
    assert len(key) == 32


def test_the_encryption_key_is_real_base64(generated):
    assert len(base64.urlsafe_b64decode(generated["DB_ENCRYPTION_KEY"] + "==")) == 32


@pytest.mark.parametrize(
    "name",
    ["BOOTSTRAP_SUPERADMIN_PASSWORD", "BOOTSTRAP_ADMIN_PASSWORD", "BOOTSTRAP_TRADER_PASSWORD"],
)
def test_login_passwords_satisfy_the_strictest_policy_in_the_codebase(generated, name):
    from security.security_manager import SecurityManager

    assert SecurityManager.validate_password(generated[name]) is True


def test_login_passwords_are_long_enough_for_the_prod_bootstrap(generated):
    """scripts/bootstrap_prod.py exits(1) below 12 characters."""
    assert len(generated["BOOTSTRAP_SUPERADMIN_PASSWORD"]) >= 12


@pytest.mark.parametrize("char", ["$", "#", "@", ":", "/", '"', "'", "\\", " ", "`"])
def test_infrastructure_passwords_avoid_characters_that_break_their_carriers(generated, char):
    """These are interpolated by docker compose ($), parsed out of .env (#),
    embedded in DSNs (@ : /) and passed to redis --requirepass."""
    for name in ("POSTGRES_PASSWORD", "DB_PASSWORD", "REDIS_PASSWORD", "GRAFANA_ADMIN_PASSWORD"):
        assert char not in generated[name], f"{name} contains {char!r}"


def test_secrets_are_not_reused_between_runs():
    a, _ = _module().generate(_TEMPLATE, _DOMAIN)
    b, _ = _module().generate(_TEMPLATE, _DOMAIN)
    assert _parse(a)["SECURITY_JWT_SECRET"] != _parse(b)["SECURITY_JWT_SECRET"]


# ── Third-party credentials are not invented ─────────────────────────────────


@pytest.mark.parametrize("name", ["BYBIT_API_KEY", "BYBIT_API_SECRET"])
def test_unfillable_third_party_keys_are_blanked_not_generated(generated, name):
    """A random Bybit key is worse than an empty one: empty reads as "disabled",
    random reads as "enabled" and fails every call at runtime."""
    assert generated[name] == ""


# ── Drift: a new placeholder cannot ship unset ───────────────────────────────


def test_every_placeholder_in_the_template_has_a_rule():
    """The anti-drift property. Adding a CHANGE_ME variable to .env.example
    without teaching this script about it fails here, not in production."""
    module = _module()
    known = set(module._GENERATORS) | set(module._ALIASES) | set(module._LEAVE_EMPTY)
    declared = {
        m.group(1)
        for m in re.finditer(r"^[^\S\n]*([A-Z0-9_]+)[^\S\n]*=[^\S\n]*CHANGE_ME\S*[^\S\n]*$", _TEMPLATE, re.MULTILINE)
    }
    assert declared, ".env.example has no standalone placeholders — has the format changed?"
    assert declared - known == set(), f"placeholders with no generation rule: {sorted(declared - known)}"


def test_an_unknown_placeholder_is_a_hard_error_not_a_passthrough():
    module = _module()
    with pytest.raises(module.GenerationError) as excinfo:
        module.generate("NEW_SECRET=CHANGE_ME_something\n", _DOMAIN)
    assert "NEW_SECRET" in str(excinfo.value)


def test_embedded_placeholders_are_covered_too():
    """A placeholder inside a composite value has no standalone assignment, so
    the sweep above cannot see it. This catches a new DSN-style variable."""
    module = _module()
    embedded = re.findall(r"^[^\S\n]*([A-Z0-9_]+)[^\S\n]*=[^\S\n]*(\S*CHANGE_ME\S*)[^\S\n]*$", _TEMPLATE, re.MULTILINE)
    composite = [name for name, value in embedded if not value.startswith("CHANGE_ME")]
    assert set(composite) <= set(module._EMBEDDED), (
        f"composite values with an unhandled embedded placeholder: {sorted(set(composite) - set(module._EMBEDDED))}"
    )


# ── Billing is optional ──────────────────────────────────────────────────────


def test_billing_is_off_so_a_deploy_without_stripe_can_start(generated):
    """Startup validation hard-fails when this is true and STRIPE_WEBHOOK_SECRET
    is empty. Stripe gets configured once the platform is running, so the
    default has to allow that order."""
    assert generated["FEATURE_BILLING_SUBSCRIPTION"] == "false"


def test_the_template_itself_ships_billing_off():
    """The generator forces it, but operators copy .env.example directly — which
    is how this failure was reached in the first place."""
    match = re.search(r"^FEATURE_BILLING_SUBSCRIPTION=(\S+)", _TEMPLATE, re.MULTILINE)
    assert match and match.group(1) == "false"


def test_both_example_files_agree_about_billing():
    """.env.production.example already defaulted it to false and documented why;
    .env.example did not. One copy fixed, the other left — again."""
    other = (_ROOT / ".env.production.example").read_text()
    match = re.search(r"^FEATURE_BILLING_SUBSCRIPTION=(\S+)", other, re.MULTILINE)
    assert match and match.group(1) == "false"


# ── Comment stripping for control-panel editors ──────────────────────────────


def test_no_comments_mode_drops_comment_lines():
    text, _ = _module().generate(_TEMPLATE, _DOMAIN, keep_comments=False)
    assert not [ln for ln in text.splitlines() if ln.strip().startswith("#")]


def test_no_comments_mode_keeps_a_value_that_legitimately_starts_with_hash():
    """.env.example carries ELITE_AM_SLACK=#elite-support, where '#' is the
    Slack channel sigil. Splitting on a bare '#' blanks it."""
    text, _ = _module().generate(_TEMPLATE, _DOMAIN, keep_comments=False)
    assert _parse(text)["ELITE_AM_SLACK"] == "#elite-support"


def test_no_comments_mode_still_strips_trailing_comments():
    text, _ = _module().generate(_TEMPLATE, _DOMAIN, keep_comments=False)
    assert _parse(text)["LOG_JSON"] == "false"


def test_no_comments_mode_still_validates(monkeypatch):
    """Stripping must not damage any value the validator reads."""
    from config.startup_validator import StartupValidationError, validate_environment

    text, _ = _module().generate(_TEMPLATE, _DOMAIN, keep_comments=False)
    env = _parse(text)
    for key in list(env):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    try:
        validate_environment(strict=True)
    except StartupValidationError as exc:
        pytest.fail(f"--no-comments output does not start in production:\n{exc}")


# ── The CLI ──────────────────────────────────────────────────────────────────


def test_it_refuses_to_overwrite_an_existing_env(tmp_path, capsys):
    """Regenerating secrets under a running deployment invalidates every session
    and locks the app out of its own database."""
    target = tmp_path / ".env"
    target.write_text("APP_ENV=production\n")
    rc = _module().main(["--domain", _DOMAIN, "--output", str(target)])
    assert rc == 1
    assert "already exists" in capsys.readouterr().err
    assert target.read_text() == "APP_ENV=production\n"


def test_force_overwrites_but_keeps_a_backup(tmp_path):
    target = tmp_path / ".env"
    target.write_text("APP_ENV=production\n")
    rc = _module().main(["--domain", _DOMAIN, "--output", str(target), "--force"])
    assert rc == 0
    assert "SECURITY_JWT_SECRET" in target.read_text()
    assert list(tmp_path.glob(".backup-*")) or list(tmp_path.glob("*.backup-*"))


def test_the_written_file_is_not_world_readable(tmp_path):
    target = tmp_path / ".env"
    assert _module().main(["--domain", _DOMAIN, "--output", str(target)]) == 0
    assert target.stat().st_mode & 0o077 == 0


# ── No variable is assigned twice ────────────────────────────────────────────


def test_no_variable_is_assigned_more_than_once():
    """A duplicate assignment in a .env is resolved by whichever line the parser
    reads last, which differs between compose, python-dotenv and shell `source`.

    This caught a real one: `_ADDITIONS` appended the bootstrap addresses
    unconditionally, so once `.env.example` declared them too, each was emitted
    twice.
    """
    import collections

    text, _ = _module().generate(_TEMPLATE, _DOMAIN)
    names = [
        line.split("=", 1)[0].strip() for line in text.splitlines() if "=" in line and not line.strip().startswith("#")
    ]
    duplicates = {n: c for n, c in collections.Counter(names).items() if c > 1}
    assert duplicates == {}, f"assigned more than once: {duplicates}"


# ── `NAME=   # comment` is not an empty value ────────────────────────────────


def test_an_empty_value_with_a_trailing_comment_is_emitted_as_truly_empty():
    """Docker compose strips an inline comment only when the value is NON-empty.

    For an empty one it takes the whole comment as the value, so

        OANDA_API_KEY=          # CANONICAL — set this one

    reaches the container as OANDA_API_KEY='# CANONICAL — set this one', and
    every ``if os.getenv("OANDA_API_KEY")`` reads it as configured. Thirty-three
    variables in .env.example had this shape, among them the OANDA credentials,
    LINEAGE_DB_URL, OTEL_EXPORTER_OTLP_ENDPOINT and both price-feed URLs —
    values that get dialled, not merely read.
    """
    text, _ = _module().generate(_TEMPLATE, _DOMAIN)
    offenders = [ln for ln in text.splitlines() if re.match(r"^[A-Z0-9_]+=[ \t]+#", ln)]
    assert offenders == [], f"these reach the container holding their own comment: {offenders[:5]}"


def test_no_generated_value_is_a_comment():
    """The same property stated over parsed values rather than raw lines."""
    text, _ = _module().generate(_TEMPLATE, _DOMAIN)
    parsed = _parse(text)
    assert [k for k, v in parsed.items() if v.startswith("#") and k != "ELITE_AM_SLACK"] == []


def test_a_value_that_legitimately_starts_with_hash_survives():
    """ELITE_AM_SLACK=#elite-support — the '#' is a Slack channel sigil.

    The discriminator is whitespace between '=' and '#', which is exactly the
    rule compose means to apply. Blanking on a bare '#' would lose this.
    """
    text, _ = _module().generate(_TEMPLATE, _DOMAIN)
    assert _parse(text)["ELITE_AM_SLACK"] == "#elite-support"


def test_a_non_empty_value_keeps_its_trailing_comment():
    """Compose handles that case correctly, so it must not be disturbed."""
    text, _ = _module().generate(_TEMPLATE, _DOMAIN)
    assert any(re.match(r"^LOG_JSON=false\s+#", ln) for ln in text.splitlines())
    assert _parse(text)["LOG_JSON"] == "false"


def test_the_comment_is_kept_rather_than_discarded():
    """The description is worth keeping; it just cannot share the line."""
    text, _ = _module().generate(_TEMPLATE, _DOMAIN)
    lines = text.splitlines()
    idx = lines.index("OANDA_API_KEY=")
    assert lines[idx - 1].lstrip().startswith("#"), "the explanation was dropped instead of moved"


def test_the_template_itself_no_longer_has_the_pattern():
    """Operators copy .env.example directly; fixing only the generator would
    leave that path broken."""
    offenders = [ln for ln in _TEMPLATE.splitlines() if re.match(r"^[A-Z0-9_]+=[ \t]+#", ln)]
    assert offenders == [], f".env.example still has {len(offenders)} such lines"


def test_the_generator_handles_the_pattern_independently_of_the_template():
    """Fixing .env.example makes the generator's guard unreachable via the real
    template, so this exercises it directly.

    Without it, a `NAME=   # comment` line reintroduced to .env.example — or
    present in any template passed with --template — would silently ship the
    comment as the value again.
    """
    template = "POSTGRES_PASSWORD=CHANGE_ME_db_password\nFOO=          # a description\nBAR=#literal-value\n"
    text, _ = _module().generate(template, _DOMAIN)
    parsed = _parse(text)

    assert parsed["FOO"] == "", f"comment shipped as the value: {parsed['FOO']!r}"
    assert parsed["BAR"] == "#literal-value", "a value with no space before '#' must survive"
    assert "# a description" in text, "the description should move, not vanish"
