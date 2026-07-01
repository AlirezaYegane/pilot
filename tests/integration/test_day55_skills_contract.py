from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SKILL_ROOT = Path("skills")


@dataclass(frozen=True)
class SkillContract:
    folder: str
    allowed_commands: tuple[str, ...]
    forbidden_phrases: tuple[str, ...]
    required_rules: tuple[str, ...]


SKILL_CONTRACTS: tuple[SkillContract, ...] = (
    SkillContract(
        folder="pilot-status",
        allowed_commands=("pilot status", "pilot budget", "pilot doctor"),
        forbidden_phrases=("git commit", "git push", "Remove-Item", "rm -rf"),
        required_rules=(
            "This skill is read-only.",
            "Do not edit files.",
            "Do not run destructive commands.",
        ),
    ),
    SkillContract(
        folder="pilot-handoff",
        allowed_commands=("pilot status", "pilot sessions", "pilot show"),
        forbidden_phrases=("git commit", "git push", "Remove-Item", "rm -rf"),
        required_rules=(
            "Do not invent facts.",
            "Do not modify project files.",
            "Do not trigger new implementation work inside this skill.",
        ),
    ),
    SkillContract(
        folder="pilot-pause",
        allowed_commands=("pilot status",),
        forbidden_phrases=("git commit", "git push", "Remove-Item", "rm -rf"),
        required_rules=(
            "Do not run additional tools unless the user explicitly approves.",
            "Wait for explicit user approval before continuing.",
            "Do not continue a failing loop.",
        ),
    ),
)


def read_skill(contract: SkillContract) -> str:
    return (SKILL_ROOT / contract.folder / "SKILL.md").read_text(encoding="utf-8")


def test_day55_skill_contracts_are_safe() -> None:
    for contract in SKILL_CONTRACTS:
        content = read_skill(contract)

        for forbidden in contract.forbidden_phrases:
            assert forbidden not in content

        for rule in contract.required_rules:
            assert rule in content


def test_day55_skill_contracts_reference_only_expected_cli_commands() -> None:
    known_cli_commands = {
        "pilot status",
        "pilot budget",
        "pilot doctor",
        "pilot sessions",
        "pilot show",
    }

    for contract in SKILL_CONTRACTS:
        content = read_skill(contract)

        for command in contract.allowed_commands:
            assert command in content

        for known_command in known_cli_commands - set(contract.allowed_commands):
            if contract.folder == "pilot-handoff" and known_command == "pilot budget":
                assert known_command not in content
            if contract.folder == "pilot-pause" and known_command != "pilot status":
                assert known_command not in content


def test_day55_handoff_skill_has_complete_handoff_shape() -> None:
    content = (SKILL_ROOT / "pilot-handoff" / "SKILL.md").read_text(encoding="utf-8")

    required_sections = (
        "Task",
        "Progress",
        "Key Decisions",
        "Files Modified",
        "Blockers",
        "Next Step",
        "Do Not Redo",
    )

    for section in required_sections:
        assert section in content


def test_day55_pause_skill_requires_user_approval_to_continue() -> None:
    content = (SKILL_ROOT / "pilot-pause" / "SKILL.md").read_text(encoding="utf-8")

    assert "Wait for explicit user approval before continuing." in content
    assert "Do not start a new implementation step." in content
