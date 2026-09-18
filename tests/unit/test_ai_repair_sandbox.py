from __future__ import annotations

from security.ai_repair_sandbox import validate_repair_source


def test_valid_source_is_checked_in_disposable_directory() -> None:
    result = validate_repair_source("class Repair:\n    pass\n")

    assert result.accepted is True
    assert result.reason_codes == ("validated_in_disposable_directory",)


def test_banned_import_is_rejected_before_execution() -> None:
    result = validate_repair_source("import os\n")

    assert result.accepted is False
    assert "banned_import:os" in result.reason_codes


def test_syntax_error_is_rejected() -> None:
    result = validate_repair_source("def broken(:\n    pass\n")

    assert result.accepted is False
    assert result.reason_codes == ("syntax_error",)


def test_empty_source_is_rejected() -> None:
    result = validate_repair_source("\n")

    assert result.accepted is False
    assert result.reason_codes == ("empty_source",)


def test_dynamic_execution_is_rejected() -> None:
    result = validate_repair_source("exec('print(1)')\n")

    assert result.accepted is False
    assert "banned_call:exec" in result.reason_codes
