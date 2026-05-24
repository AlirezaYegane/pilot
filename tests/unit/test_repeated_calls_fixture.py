from __future__ import annotations

import json
from pathlib import Path

from pilot_core.constants import Severity
from pilot_core.signals.repeated_calls import evaluate_repeated_calls


def test_repeated_calls_fixture_triggers_signal() -> None:
    fixture_path = Path("tests/fixtures/repeated_calls.jsonl")
    calls = [
        json.loads(line)
        for line in fixture_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    result = evaluate_repeated_calls(calls)

    assert result.score >= 0.65
    assert result.severity in {Severity.WARNING, Severity.CRITICAL}
    assert result.repeat_count >= 3
    assert result.repeated_fingerprint is not None
    assert result.repeated_fingerprint.tool_name == "Bash"
