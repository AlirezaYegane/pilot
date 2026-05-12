from __future__ import annotations

from pathlib import Path

from pilot_core.safety import (
    fail_silent,
    log_exception,
    run_safely,
    safe_string,
    utc_timestamp,
    write_debug_log,
)


def test_safe_string_handles_plain_strings() -> None:
    assert safe_string("hello") == "hello"


def test_safe_string_handles_unserialisable_objects() -> None:
    class WeirdObject:
        pass

    value = safe_string({"item": WeirdObject()})
    assert "WeirdObject" in value


def test_safe_string_truncates_long_text() -> None:
    value = safe_string("x" * 20, limit=5)
    assert value == "xxxxx... [truncated]"


def test_write_debug_log_creates_log_file(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "debug.log"

    write_debug_log("hello from test", debug_log_path=log_path)

    assert log_path.exists()
    assert "hello from test" in log_path.read_text(encoding="utf-8")


def test_log_exception_writes_exception_type(tmp_path: Path) -> None:
    log_path = tmp_path / "debug.log"

    log_exception(ValueError("boom"), context="unit-test", debug_log_path=log_path)

    content = log_path.read_text(encoding="utf-8")
    assert "unit-test" in content
    assert "ValueError" in content
    assert "boom" in content


def test_run_safely_returns_result_when_successful(tmp_path: Path) -> None:
    log_path = tmp_path / "debug.log"

    result = run_safely(lambda: "ok", default="fallback", debug_log_path=log_path)

    assert result == "ok"
    assert not log_path.exists()


def test_run_safely_returns_default_when_operation_fails(tmp_path: Path) -> None:
    log_path = tmp_path / "debug.log"

    def broken() -> str:
        raise RuntimeError("broken operation")

    result = run_safely(
        broken,
        default="fallback",
        context="broken-test",
        debug_log_path=log_path,
    )

    assert result == "fallback"
    assert "broken-test" in log_path.read_text(encoding="utf-8")


def test_fail_silent_decorator_returns_default_on_error(tmp_path: Path) -> None:
    log_path = tmp_path / "debug.log"

    @fail_silent("fallback", context="decorator-test", debug_log_path=log_path)
    def broken() -> str:
        raise RuntimeError("decorator boom")

    assert broken() == "fallback"

    content = log_path.read_text(encoding="utf-8")
    assert "decorator-test" in content
    assert "decorator boom" in content


def test_utc_timestamp_is_iso_like() -> None:
    value = utc_timestamp()
    assert "T" in value
    assert "+00:00" in value
