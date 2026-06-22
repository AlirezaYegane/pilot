"""Day 44 handoff extractor smoke report."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_demo_db() -> sqlite3.Connection:
    """Build a small in-memory DB that mimics early Pilot storage."""

    connection = sqlite3.connect(":memory:")

    connection.execute(
        """
        CREATE TABLE session_turns (
            session_id TEXT,
            turn_index INTEGER,
            role TEXT,
            content TEXT,
            summary TEXT,
            tool_name TEXT,
            file_path TEXT,
            success INTEGER,
            timestamp_ms INTEGER
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE signal_results (
            session_id TEXT,
            turn_index INTEGER,
            signal_name TEXT,
            score REAL,
            fired INTEGER,
            severity TEXT,
            timestamp_ms INTEGER
        )
        """
    )

    connection.executemany(
        """
        INSERT INTO session_turns
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "smoke-day44",
                1,
                "user",
                "Implement Day 44 handoff summary extractor",
                "",
                "",
                "",
                1,
                1000,
            ),
            (
                "smoke-day44",
                2,
                "assistant",
                "",
                "Decision: extract from DB into HandoffSchema, not markdown",
                "",
                "",
                1,
                2000,
            ),
            (
                "smoke-day44",
                3,
                "tool",
                "",
                "Created extractor module",
                "Write",
                "pilot_core/handoff_extractor.py",
                1,
                3000,
            ),
            (
                "smoke-day44",
                4,
                "assistant",
                "",
                "Next step: run targeted gate and full pre-commit",
                "",
                "",
                1,
                4000,
            ),
        ],
    )

    connection.executemany(
        """
        INSERT INTO signal_results
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("smoke-day44", 2, "token_burn", 0.15, 0, "info", 2100),
            ("smoke-day44", 4, "error_cascade", 0.82, 1, "warning", 4100),
        ],
    )

    connection.commit()
    return connection


def main() -> None:
    """Run Day 44 smoke extraction."""

    from pilot_core.handoff import handoff_summary
    from pilot_core.handoff_extractor import (
        extract_handoff_from_db,
        handoff_extraction_summary,
    )

    connection = build_demo_db()
    result = extract_handoff_from_db(connection, session_id="smoke-day44")

    report = {
        "extraction": handoff_extraction_summary(result),
        "handoff_summary": handoff_summary(result.handoff),
        "key_turns": [
            {
                "turn_index": turn.turn_index,
                "role": turn.role,
                "tool_name": turn.tool_name,
                "file_path": turn.file_path,
                "success": turn.success,
                "text": turn.display_text,
            }
            for turn in result.key_turns
        ],
        "signal_history": [
            {
                "turn_index": signal.turn_index,
                "signal_name": signal.signal_name,
                "score": signal.score,
                "fired": signal.fired,
                "severity": signal.severity,
            }
            for signal in result.signal_history
        ],
        "payload_preview": result.handoff.to_dict(),
    }

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
