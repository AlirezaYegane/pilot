from __future__ import annotations

from pilot_core.constants import SessionState
from pilot_core.health import compute_health_score
from tests.integration.test_day35_full_signal_integration import (
    FIXTURE_DIR,
    evaluate_all_signals,
    fired_signals,
    read_jsonl,
)


def test_day36_healthy_replay_case_stays_healthy() -> None:
    records = read_jsonl(FIXTURE_DIR / "healthy_session.jsonl")
    signal_results = evaluate_all_signals(records)

    health = compute_health_score(signal_results)

    assert health.health_score >= 0.80
    assert health.derived_state is SessionState.HEALTHY
    assert health.fired_count == 0


def test_day36_noisy_replay_case_does_not_escalate() -> None:
    records = read_jsonl(FIXTURE_DIR / "noisy_session.jsonl")
    signal_results = evaluate_all_signals(records)

    health = compute_health_score(signal_results)

    assert health.health_score >= 0.60
    assert health.derived_state in {SessionState.HEALTHY, SessionState.WATCHING}
    assert health.should_escalate is False


def test_day36_ambiguous_replay_case_does_not_become_critical() -> None:
    records = read_jsonl(FIXTURE_DIR / "ambiguous_session.jsonl")
    signal_results = evaluate_all_signals(records)

    health = compute_health_score(signal_results)

    assert health.health_score >= 0.40
    assert health.derived_state is not SessionState.CRITICAL


def test_day36_degraded_replay_case_becomes_critical_or_degrading() -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")
    signal_results = evaluate_all_signals(records)

    health = compute_health_score(signal_results)
    fired_names = fired_signals(signal_results)

    assert len(fired_names) >= 5
    assert health.health_score < 0.60
    assert health.derived_state in {SessionState.DEGRADING, SessionState.CRITICAL}
    assert health.should_escalate is True


def test_day36_degraded_top_contributors_are_non_empty() -> None:
    records = read_jsonl(FIXTURE_DIR / "degraded_session.jsonl")
    signal_results = evaluate_all_signals(records)

    health = compute_health_score(signal_results)
    top = health.top_contributors

    assert top
    assert top[0].weighted_badness > 0.0
    assert top[0].signal_name in signal_results
