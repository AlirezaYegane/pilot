from __future__ import annotations

import json

import pytest

from pilot_core.handoff import (
    HANDOFF_SCHEMA_VERSION,
    HandoffBlocker,
    HandoffBlockerSeverity,
    HandoffDecision,
    HandoffDoNotRedo,
    HandoffFileChange,
    HandoffFileStatus,
    HandoffSchema,
    create_empty_handoff,
    handoff_from_dict,
    handoff_from_json,
    handoff_summary,
    handoff_to_json,
)


def test_create_empty_handoff_is_valid() -> None:
    handoff = create_empty_handoff(
        session_id="session-1",
        task="Implement Day 43 handoff schema",
        progress="Schema created",
        next_step="Add extractor from DB",
    )

    assert handoff.schema_version == HANDOFF_SCHEMA_VERSION
    assert handoff.session_id == "session-1"
    assert handoff.is_valid()
    assert handoff.validation_errors() == tuple()
    assert handoff.generated_at


def test_handoff_schema_validation_requires_core_fields() -> None:
    handoff = HandoffSchema(task="", progress="", next_step="")

    assert not handoff.is_valid()

    errors = handoff.validation_errors()
    assert "task is required" in errors
    assert "progress is required" in errors
    assert "next_step is required" in errors


def test_handoff_schema_supports_full_contract() -> None:
    handoff = HandoffSchema(
        session_id="session-2",
        task="Finish policy runtime",
        progress="Runtime pipeline is green",
        decisions=(
            HandoffDecision(
                title="Keep runtime side-effect free",
                rationale="Hooks should call pure code and handle IO separately.",
                alternatives_rejected=("write to storage from runtime",),
            ),
        ),
        files_modified=(
            HandoffFileChange(
                path="pilot_core/policy_runtime.py",
                status=HandoffFileStatus.CREATED,
                reason="central runtime pipeline",
            ),
        ),
        blockers=(
            HandoffBlocker(
                description="Stop hook integration is not wired yet",
                severity=HandoffBlockerSeverity.WARNING,
                evidence="Day 42 explicitly stays side-effect free",
            ),
        ),
        next_step="Implement DB summary extractor",
        do_not_redo=(
            HandoffDoNotRedo(
                item="Do not wire stop hook before schema and renderer are stable",
                reason="handoff contract needs to stay stable first",
            ),
        ),
        notes=("Ready for Week 7 handoff engine",),
    )

    assert handoff.is_valid()
    assert handoff.has_blockers
    assert handoff.has_do_not_redo_items

    data = handoff.to_dict()
    assert data["task"] == "Finish policy runtime"
    assert data["decisions"] == [
        {
            "title": "Keep runtime side-effect free",
            "rationale": "Hooks should call pure code and handle IO separately.",
            "alternatives_rejected": ["write to storage from runtime"],
        }
    ]


def test_handoff_json_round_trip() -> None:
    handoff = HandoffSchema(
        session_id="session-3",
        task="Build handoff schema",
        progress="Data contract implemented",
        decisions=(HandoffDecision(title="Use dataclasses"),),
        files_modified=(
            HandoffFileChange(
                path="pilot_core/handoff.py",
                status=HandoffFileStatus.CREATED,
            ),
        ),
        blockers=tuple(),
        next_step="Write markdown renderer",
        do_not_redo=(HandoffDoNotRedo(item="Do not skip schema tests"),),
        notes=("round trip test",),
    )

    text = handoff_to_json(handoff)
    parsed = handoff_from_json(text)

    assert parsed == handoff
    assert json.loads(text)["schema_version"] == HANDOFF_SCHEMA_VERSION


def test_handoff_from_dict_normalises_nested_records() -> None:
    handoff = handoff_from_dict(
        {
            "schema_version": HANDOFF_SCHEMA_VERSION,
            "session_id": "session-4",
            "generated_at": "2026-06-22T00:00:00+00:00",
            "task": "Normalise handoff",
            "progress": "Raw dict parsed",
            "decisions": [
                {
                    "title": "Use explicit schema",
                    "rationale": "Stable future renderer",
                    "alternatives_rejected": ["free-form text only"],
                }
            ],
            "files_modified": [
                {
                    "path": "pilot_core/handoff.py",
                    "status": "modified",
                    "reason": "schema",
                    "important": "true",
                }
            ],
            "blockers": [
                {
                    "description": "Renderer not implemented",
                    "severity": "error",
                    "evidence": "Day 46 scope",
                }
            ],
            "next_step": "Implement extractor",
            "do_not_redo": [
                {
                    "item": "Do not generate markdown yet",
                    "reason": "Day 43 only defines schema",
                }
            ],
            "notes": ["note A", ""],
        }
    )

    assert handoff.session_id == "session-4"
    assert handoff.generated_at == "2026-06-22T00:00:00+00:00"
    assert handoff.decisions[0].alternatives_rejected == ("free-form text only",)
    assert handoff.files_modified[0].status is HandoffFileStatus.MODIFIED
    assert handoff.files_modified[0].important is True
    assert handoff.blockers[0].severity is HandoffBlockerSeverity.ERROR
    assert handoff.notes == ("note A",)


def test_handoff_from_dict_handles_unknown_enums_safely() -> None:
    handoff = handoff_from_dict(
        {
            "task": "Unknown enum handling",
            "progress": "Parsed",
            "next_step": "Continue",
            "files_modified": [{"path": "x.py", "status": "weird"}],
            "blockers": [{"description": "Something happened", "severity": "weird"}],
        }
    )

    assert handoff.files_modified[0].status is HandoffFileStatus.UNKNOWN
    assert handoff.blockers[0].severity is HandoffBlockerSeverity.WARNING


def test_handoff_from_json_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        handoff_from_json("[]")


def test_handoff_summary_is_compact_and_serialisable() -> None:
    handoff = HandoffSchema(
        task="Summarise work",
        progress="Schema ready",
        decisions=(HandoffDecision(title="Decision A"),),
        files_modified=(HandoffFileChange(path="pilot_core/handoff.py"),),
        blockers=(HandoffBlocker(description="Blocker A"),),
        next_step="Run tests",
        do_not_redo=(HandoffDoNotRedo(item="Bad attempt"),),
    )

    summary = handoff_summary(handoff)

    assert summary["decision_count"] == 1
    assert summary["file_count"] == 1
    assert summary["blocker_count"] == 1
    assert summary["do_not_redo_count"] == 1
    assert summary["has_blockers"] is True
    assert summary["is_valid"] is True
    assert summary["validation_errors"] == []
