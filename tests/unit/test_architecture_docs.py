from __future__ import annotations

from pathlib import Path

ADR_DIR = Path("docs/adr")

REQUIRED_ADRS: dict[str, tuple[str, ...]] = {
    "ADR-001-local-first.md": (
        "local-first",
        "SQLite",
        "pilot_core.paths",
        "ensure_runtime_dirs",
    ),
    "ADR-002-hook-safety.md": (
        "never-break-the-user",
        "log_exception",
        "stdout",
        "pre-hook",
    ),
    "ADR-003-silent-failure-philosophy.md": (
        "fail-silent",
        "run_safely",
        "fail_silent",
        "safe_string",
    ),
    "ADR-004-hook-latency.md": (
        "PreToolUse",
        "p95",
        "30ms",
        "benchmarks",
    ),
    "ADR-005-runtime-path-strategy.md": (
        "RuntimePaths",
        "resolve_runtime_paths",
        "debug_log_path",
        "db_path",
    ),
}

REQUIRED_SECTIONS = (
    "## Status",
    "## Context",
    "## Decision",
    "## Consequences",
    "## Implementation rules",
    "## Verification",
)


def read_doc(filename: str) -> str:
    return (ADR_DIR / filename).read_text(encoding="utf-8")


def test_adr_directory_exists() -> None:
    assert ADR_DIR.is_dir()


def test_required_architecture_decision_records_exist() -> None:
    for filename in REQUIRED_ADRS:
        assert (ADR_DIR / filename).is_file(), f"Missing ADR: {filename}"


def test_architecture_decision_records_have_required_sections() -> None:
    for filename in sorted(REQUIRED_ADRS):
        content = read_doc(filename)

        for section in REQUIRED_SECTIONS:
            assert section in content, f"{filename} missing section {section}"


def test_architecture_decision_records_include_required_terms() -> None:
    for filename, required_terms in REQUIRED_ADRS.items():
        content = read_doc(filename).lower()
        missing_terms = [term for term in required_terms if term.lower() not in content]

        assert not missing_terms, f"{filename} missing terms: {missing_terms}"


def test_adr_index_references_all_required_records() -> None:
    index = read_doc("README.md")

    for filename in REQUIRED_ADRS:
        assert filename in index


def test_architecture_overview_exists_and_links_to_adr_directory() -> None:
    overview = Path("docs/architecture.md")
    assert overview.is_file()

    content = overview.read_text(encoding="utf-8")
    assert "docs/adr/" in content
    assert "local-first" in content.lower()
    assert "never break" in content.lower()
