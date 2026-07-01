from __future__ import annotations

from pathlib import Path

SKILL_ROOT = Path("skills")

EXPECTED_SKILLS: dict[str, tuple[str, ...]] = {
    "pilot-status": (
        "pilot status",
        "pilot budget",
        "pilot doctor",
        "read-only",
        "Do not edit files",
    ),
    "pilot-handoff": (
        "pilot sessions",
        "pilot show",
        "Task",
        "Progress",
        "Next Step",
        "Do Not Redo",
        "Do not invent facts",
    ),
    "pilot-pause": (
        "pilot status",
        "Do not run additional tools",
        "Wait for explicit user approval",
        "resume point",
    ),
}


def read_skill(skill_name: str) -> str:
    return (SKILL_ROOT / skill_name / "SKILL.md").read_text(encoding="utf-8")


def test_day55_skill_files_exist() -> None:
    missing: list[str] = []

    for skill_name in EXPECTED_SKILLS:
        path = SKILL_ROOT / skill_name / "SKILL.md"
        if not path.exists():
            missing.append(str(path))

    assert missing == []


def test_day55_skills_have_frontmatter() -> None:
    for skill_name in EXPECTED_SKILLS:
        content = read_skill(skill_name)

        assert content.startswith("---\n")
        assert "name: " in content
        assert "description: " in content
        assert "\n---\n" in content


def test_day55_skills_have_required_content() -> None:
    for skill_name, required_phrases in EXPECTED_SKILLS.items():
        content = read_skill(skill_name)

        for phrase in required_phrases:
            assert phrase in content


def test_day55_skills_have_goal_workflow_and_safety_sections() -> None:
    required_headings = ("## Goal", "## Safe workflow", "## Safety rules")

    for skill_name in EXPECTED_SKILLS:
        content = read_skill(skill_name)

        for heading in required_headings:
            assert heading in content


def test_day55_skills_are_not_empty_placeholders() -> None:
    for skill_name in EXPECTED_SKILLS:
        content = read_skill(skill_name)
        non_empty_lines = [line for line in content.splitlines() if line.strip()]

        assert len(non_empty_lines) >= 25
        assert "TODO" not in content
        assert "placeholder" not in content.lower()
