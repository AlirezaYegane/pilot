"""Day 48 session-start resume smoke report."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    """Create a Day 47-style handoff and load it through SessionStart resume."""

    from pilot_core.handoff import HandoffBlocker, HandoffDoNotRedo, HandoffSchema
    from pilot_core.render.handoff_md import (
        HandoffMarkdownOptions,
        HandoffMarkdownStyle,
        render_handoff_markdown,
    )
    from pilot_core.session_resume import (
        generate_session_resume_from_payload,
        session_resume_summary,
    )
    from pilot_core.stop_handoff import DEFAULT_STOP_HANDOFF_DIR, write_stop_handoff_artifacts

    with TemporaryDirectory() as temp_dir:
        cwd = Path(temp_dir)
        handoff_dir = cwd / DEFAULT_STOP_HANDOFF_DIR

        handoff = HandoffSchema(
            session_id="smoke-day47-previous",
            generated_at="2026-06-23T00:00:00+00:00",
            task="Continue after generated stop-hook handoff",
            progress="Day 47 wrote markdown and JSON handoff artifacts.",
            blockers=(
                HandoffBlocker(
                    description="SessionStart resume flow was not wired yet",
                    evidence="Day 48 owns loading the previous handoff.",
                ),
            ),
            next_step="Load this handoff at SessionStart and inject it as additionalContext.",
            do_not_redo=(
                HandoffDoNotRedo(
                    item="Do not ignore the previous handoff",
                    reason="The next session needs the preserved blocker and next step.",
                ),
            ),
            notes=("Smoke confirms the new session sees the previous context.",),
        )

        markdown = render_handoff_markdown(
            handoff,
            options=HandoffMarkdownOptions(style=HandoffMarkdownStyle.FULL),
        )
        markdown_path, json_path = write_stop_handoff_artifacts(
            handoff=handoff,
            markdown=markdown,
            handoff_dir=handoff_dir,
        )

        result = generate_session_resume_from_payload(
            {
                "session_id": "smoke-day48-new-session",
                "cwd": str(cwd),
                "model": "smoke-model",
                "timestamp_ms": 123456789,
            },
            record_session=False,
        )

        report = {
            "created_artifacts": {
                "markdown_path": str(markdown_path),
                "json_path": str(json_path),
                "markdown_exists": markdown_path.exists(),
                "json_exists": json_path.exists(),
            },
            "resume": session_resume_summary(result),
        }

        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
