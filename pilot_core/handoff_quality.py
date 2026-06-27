"""Handoff quality review helpers for Pilot.

Day 49 adds replay-oriented quality checks for generated handoff summaries.

The goal is not to judge writing style perfectly. The goal is to catch
handoffs that are technically unusable:

- missing required sections
- missing next step
- missing blocker/do-not-redo sections when schema contains them
- invalid schema rendered as markdown
- empty placeholder text
- extremely long or tiny summaries
- unreadable generated artifacts

This module is pure and side-effect free.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pilot_core.handoff import HandoffSchema, handoff_from_json
from pilot_core.render.handoff_md import (
    HandoffMarkdownOptions,
    HandoffMarkdownStyle,
    render_handoff_markdown,
)

REQUIRED_HANDOFF_HEADINGS = (
    "# Pilot Handoff",
    "## Task",
    "## Progress",
    "## Next Step",
)

MAX_RECOMMENDED_HANDOFF_CHARS = 12_000
MIN_RECOMMENDED_HANDOFF_CHARS = 120


@dataclass(frozen=True)
class HandoffQualityIssue:
    """One quality issue found in a generated handoff."""

    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class HandoffQualityReview:
    """Quality review result for one generated handoff markdown."""

    score: float
    passed: bool
    issues: tuple[HandoffQualityIssue, ...]
    line_count: int
    char_count: int
    required_heading_count: int
    source_format: str
    explanation: str

    @property
    def issue_count(self) -> int:
        """Return total issue count."""

        return len(self.issues)

    @property
    def error_count(self) -> int:
        """Return number of error-level issues."""

        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        """Return number of warning-level issues."""

        return sum(1 for issue in self.issues if issue.severity == "warning")


def clamp_score(value: float) -> float:
    """Clamp quality score into 0..1."""

    return max(0.0, min(1.0, value))


def _clean_text(value: object) -> str:
    """Return compact text."""

    return " ".join(str(value).strip().split())


def _has_heading(markdown: str, heading: str) -> bool:
    """Return True when markdown contains a heading exactly."""

    return heading in markdown.splitlines()


def _issue(code: str, severity: str, message: str) -> HandoffQualityIssue:
    """Create a quality issue."""

    return HandoffQualityIssue(code=code, severity=severity, message=message)


def _score_from_issues(issues: Sequence[HandoffQualityIssue]) -> float:
    """Convert issues to a deterministic quality score."""

    score = 1.0

    for issue in issues:
        if issue.severity == "error":
            score -= 0.25
        elif issue.severity == "warning":
            score -= 0.10
        else:
            score -= 0.03

    return clamp_score(score)


def _required_heading_count(markdown: str) -> int:
    """Return number of required headings present."""

    return sum(1 for heading in REQUIRED_HANDOFF_HEADINGS if _has_heading(markdown, heading))


def _has_actionable_next_step(markdown: str) -> bool:
    """Return True when the Next Step section looks actionable enough."""

    lowered = markdown.lower()

    if "## next step" not in lowered:
        return False

    action_markers = (
        "continue",
        "start",
        "run",
        "fix",
        "load",
        "review",
        "implement",
        "test",
        "merge",
        "push",
        "next",
    )
    return any(marker in lowered for marker in action_markers)


def _review_schema_specific_rules(
    handoff: HandoffSchema | None,
    markdown: str,
) -> list[HandoffQualityIssue]:
    """Return issues that require the original HandoffSchema."""

    issues: list[HandoffQualityIssue] = []

    if handoff is None:
        return issues

    for error in handoff.validation_errors():
        issues.append(
            _issue(
                "schema_validation_error",
                "error",
                f"Handoff schema validation failed: {error}",
            )
        )

    if handoff.blockers and not _has_heading(markdown, "## Blockers"):
        issues.append(
            _issue(
                "missing_blockers_section",
                "error",
                "Schema contains blockers, but markdown has no Blockers section.",
            )
        )

    if handoff.do_not_redo and not _has_heading(markdown, "## Do Not Redo"):
        issues.append(
            _issue(
                "missing_do_not_redo_section",
                "error",
                "Schema contains do-not-redo items, but markdown has no Do Not Redo section.",
            )
        )

    if handoff.files_modified and not _has_heading(markdown, "## Files Modified"):
        issues.append(
            _issue(
                "missing_files_modified_section",
                "warning",
                "Schema contains file changes, but markdown has no Files Modified section.",
            )
        )

    if handoff.blockers and not handoff.do_not_redo:
        issues.append(
            _issue(
                "blockers_without_do_not_redo",
                "warning",
                "Handoff has blockers but no do-not-redo guidance.",
            )
        )

    return issues


def review_handoff_markdown_text(
    markdown: str,
    *,
    handoff: HandoffSchema | None = None,
    source_format: str = "markdown",
    minimum_score: float = 0.80,
) -> HandoffQualityReview:
    """Review rendered handoff markdown."""

    text = markdown.strip()
    lines = text.splitlines()
    issues: list[HandoffQualityIssue] = []

    if not text:
        issues.append(_issue("empty_markdown", "error", "Generated handoff markdown is empty."))

    for heading in REQUIRED_HANDOFF_HEADINGS:
        if not _has_heading(text, heading):
            issues.append(
                _issue(
                    "missing_required_heading",
                    "error",
                    f"Missing required heading: {heading}",
                )
            )

    if "_Missing task._" in text:
        issues.append(
            _issue(
                "missing_task_placeholder", "error", "Task section contains missing placeholder."
            )
        )

    if "_Missing progress._" in text:
        issues.append(
            _issue(
                "missing_progress_placeholder",
                "error",
                "Progress section contains missing placeholder.",
            )
        )

    if "_Missing next step._" in text:
        issues.append(
            _issue(
                "missing_next_step_placeholder",
                "error",
                "Next Step section contains missing placeholder.",
            )
        )

    if len(text) < MIN_RECOMMENDED_HANDOFF_CHARS:
        issues.append(
            _issue(
                "handoff_too_short",
                "warning",
                "Handoff is very short and may not contain enough resume context.",
            )
        )

    if len(text) > MAX_RECOMMENDED_HANDOFF_CHARS:
        issues.append(
            _issue(
                "handoff_too_long",
                "warning",
                "Handoff is very long and may be noisy for resume context.",
            )
        )

    if not _has_actionable_next_step(text):
        issues.append(
            _issue(
                "next_step_not_actionable",
                "warning",
                "Next Step section does not look actionable enough.",
            )
        )

    issues.extend(_review_schema_specific_rules(handoff, text))

    score = _score_from_issues(issues)
    passed = score >= minimum_score and not any(issue.severity == "error" for issue in issues)

    explanation = (
        f"Handoff quality score {score:.2f}; "
        f"{len(issues)} issue(s), "
        f"{sum(1 for issue in issues if issue.severity == 'error')} error(s)."
    )

    return HandoffQualityReview(
        score=score,
        passed=passed,
        issues=tuple(issues),
        line_count=len(lines),
        char_count=len(text),
        required_heading_count=_required_heading_count(text),
        source_format=source_format,
        explanation=explanation,
    )


def review_handoff_markdown(
    handoff: HandoffSchema,
    *,
    markdown: str | None = None,
    minimum_score: float = 0.80,
) -> HandoffQualityReview:
    """Render and review a handoff schema."""

    rendered = markdown
    if rendered is None:
        rendered = render_handoff_markdown(
            handoff,
            options=HandoffMarkdownOptions(style=HandoffMarkdownStyle.FULL),
        )

    return review_handoff_markdown_text(
        rendered,
        handoff=handoff,
        source_format="schema",
        minimum_score=minimum_score,
    )


def review_handoff_artifact(path: str | Path) -> HandoffQualityReview:
    """Review a handoff artifact from disk."""

    artifact_path = Path(path)
    text = artifact_path.read_text(encoding="utf-8")
    suffix = artifact_path.suffix.lower()

    if suffix == ".json":
        handoff = handoff_from_json(text)
        return review_handoff_markdown(handoff)

    if suffix == ".md":
        return review_handoff_markdown_text(text, source_format="markdown")

    raise ValueError(f"Unsupported handoff artifact type: {artifact_path}")


def handoff_quality_summary(review: HandoffQualityReview) -> dict[str, object]:
    """Return a compact serialisable quality summary."""

    return {
        "score": round(review.score, 4),
        "passed": review.passed,
        "issue_count": review.issue_count,
        "error_count": review.error_count,
        "warning_count": review.warning_count,
        "line_count": review.line_count,
        "char_count": review.char_count,
        "required_heading_count": review.required_heading_count,
        "source_format": review.source_format,
        "issues": [
            {
                "code": issue.code,
                "severity": issue.severity,
                "message": issue.message,
            }
            for issue in review.issues
        ],
        "explanation": review.explanation,
    }


def handoff_quality_summary_json(review: HandoffQualityReview) -> str:
    """Return pretty JSON for quality review output."""

    return json.dumps(handoff_quality_summary(review), indent=2, sort_keys=True)
