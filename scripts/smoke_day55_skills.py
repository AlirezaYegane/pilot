"""Day 55 smoke test for Pilot skills."""

from __future__ import annotations

import json
from pathlib import Path

SKILL_ROOT = Path("skills")
SKILL_NAMES = ("pilot-status", "pilot-handoff", "pilot-pause")


def _skill_path(skill_name: str) -> Path:
    return SKILL_ROOT / skill_name / "SKILL.md"


def _has_frontmatter(content: str) -> bool:
    return content.startswith("---\n") and "\n---\n" in content


def _summary_for_skill(skill_name: str) -> dict[str, object]:
    path = _skill_path(skill_name)
    content = path.read_text(encoding="utf-8")
    lines = [line for line in content.splitlines() if line.strip()]

    return {
        "skill": skill_name,
        "path": str(path),
        "exists": path.exists(),
        "line_count": len(lines),
        "has_frontmatter": _has_frontmatter(content),
        "has_goal": "## Goal" in content,
        "has_safe_workflow": "## Safe workflow" in content,
        "has_safety_rules": "## Safety rules" in content,
        "mentions_pilot_cli": "pilot " in content,
    }


def main() -> int:
    summaries = [_summary_for_skill(skill_name) for skill_name in SKILL_NAMES]

    result = {
        "day": 55,
        "skill_count": len(summaries),
        "skills": summaries,
        "all_passed": all(
            bool(item["exists"])
            and bool(item["has_frontmatter"])
            and bool(item["has_goal"])
            and bool(item["has_safe_workflow"])
            and bool(item["has_safety_rules"])
            for item in summaries
        ),
    }

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
