from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _write_config(temp_root: Path) -> Path:
    data_dir = temp_root / "pilot-data"
    debug_log_path = temp_root / "debug.log"
    config_path = temp_root / "pilot.yaml"

    config_path.write_text(
        f"""
storage:
  data_dir: "{data_dir.as_posix()}"
  debug_log_path: "{debug_log_path.as_posix()}"
  handoff_dir_name: handoffs
""".strip()
        + "\n",
        encoding="utf-8",
    )

    return config_path


def _create_sessions_table(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                started_at INTEGER NOT NULL,
                ended_at INTEGER,
                cwd TEXT,
                model TEXT,
                state TEXT DEFAULT 'healthy',
                handoff_summary_path TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO sessions (id, started_at, state) VALUES (?, ?, ?);",
            ("day21-smoke-session", 1, "critical"),
        )
        conn.commit()
    finally:
        conn.close()


def _run_hook(
    hook_name: str,
    payload: dict[str, object],
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "hooks" / hook_name)],
        cwd=PROJECT_ROOT,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pilot-day21-", ignore_cleanup_errors=True) as temp_dir:
        temp_root = Path(temp_dir)
        config_path = _write_config(temp_root)
        data_dir = temp_root / "pilot-data"
        db_path = data_dir / "pilot.db"
        _create_sessions_table(db_path)

        env = os.environ.copy()
        env["CLAUDE_PLUGIN_ROOT"] = str(PROJECT_ROOT)
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        env["PILOT_CONFIG"] = str(config_path)

        payload = {
            "session_id": "day21-smoke-session",
            "cwd": str(PROJECT_ROOT),
            "model": "smoke-model",
            "timestamp_ms": 123456789,
        }

        stop_result = _run_hook("stop.py", payload, env)
        if stop_result.returncode != 0:
            print(stop_result.stdout)
            print(stop_result.stderr)
            return 1

        if "additionalContext" not in stop_result.stdout:
            print("Stop hook did not emit expected additionalContext for critical session.")
            print("stdout:", stop_result.stdout)
            print("stderr:", stop_result.stderr)
            return 1

        end_result = _run_hook("session_end.py", payload, env)
        if end_result.returncode != 0:
            print(end_result.stdout)
            print(end_result.stderr)
            return 1

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT ended_at, handoff_summary_path, state FROM sessions WHERE id = ?;",
                ("day21-smoke-session",),
            ).fetchone()
        finally:
            conn.close()

        if row is None:
            print("Session row missing after hooks.")
            return 1

        ended_at, handoff_summary_path, state = row
        if ended_at is None:
            print("SessionEnd hook did not set ended_at.")
            return 1

        if not handoff_summary_path or not Path(str(handoff_summary_path)).exists():
            print("Handoff placeholder was not written.")
            return 1

        if state != "handoff_pending":
            print(f"Expected handoff_pending state after Stop hook, got {state!r}.")
            return 1

        print(
            json.dumps(
                {
                    "status": "passed",
                    "session_id": "day21-smoke-session",
                    "db_path": str(db_path),
                    "handoff_summary_path": str(handoff_summary_path),
                },
                indent=2,
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
