from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_user_prompt_submit_hook_records_turn(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PILOT_DATA_DIR"] = str(tmp_path / "pilot-data")

    payload = {
        "session_id": "hook-session-1",
        "transcript_path": str(tmp_path / "transcript.jsonl"),
        "cwd": str(tmp_path),
        "permission_mode": "default",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "Hello from hook test",
    }

    completed = subprocess.run(
        [sys.executable, "hooks/user_prompt_submit.py"],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == ""

    db_path = tmp_path / "pilot-data" / "pilot.db"
    assert db_path.exists()

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT session_id, turn_index, user_prompt_preview,
                   tool_count, error_count
            FROM turns
            WHERE session_id = ?;
            """,
            ("hook-session-1",),
        ).fetchone()

    assert row == ("hook-session-1", 0, "Hello from hook test", 0, 0)
