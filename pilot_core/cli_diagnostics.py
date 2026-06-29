"""Doctor CLI diagnostics for Pilot.

Day 54 adds install, DB, and hook diagnostics for:

    pilot doctor

Diagnostics are intentionally defensive and mostly non-fatal. Missing optional
local runtime state is usually WARN, while broken project/plugin files are FAIL.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import py_compile
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pilot_core.cli_budget import default_budget_db_candidates, find_existing_budget_db

REQUIRED_HOOK_FILES = (
    "session_start.py",
    "user_prompt_submit.py",
    "pre_tool_use.py",
    "post_tool_use.py",
    "post_tool_failure.py",
    "stop.py",
    "session_end.py",
)

REQUIRED_DB_TABLES = (
    "sessions",
    "turns",
    "tool_uses",
    "signals",
)


@dataclass(frozen=True)
class DiagnosticCheck:
    """One doctor diagnostic row."""

    name: str
    status: str
    message: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        """Return True when check status is OK."""

        return self.status == "OK"

    @property
    def warning(self) -> bool:
        """Return True when check status is WARN."""

        return self.status == "WARN"

    @property
    def failed(self) -> bool:
        """Return True when check status is FAIL."""

        return self.status == "FAIL"


@dataclass(frozen=True)
class DiagnosticReport:
    """Full doctor diagnostic report."""

    checks: tuple[DiagnosticCheck, ...]

    @property
    def failed_count(self) -> int:
        """Return number of failed checks."""

        return sum(1 for check in self.checks if check.failed)

    @property
    def warning_count(self) -> int:
        """Return number of warnings."""

        return sum(1 for check in self.checks if check.warning)

    @property
    def ok_count(self) -> int:
        """Return number of OK checks."""

        return sum(1 for check in self.checks if check.ok)

    @property
    def exit_code(self) -> int:
        """Return CLI exit code."""

        return 1 if self.failed_count else 0

    @property
    def status(self) -> str:
        """Return overall report status."""

        if self.failed_count:
            return "FAIL"

        if self.warning_count:
            return "WARN"

        return "OK"


def discover_project_root(start: str | Path | None = None) -> Path:
    """Discover project root from current path."""

    current = Path(start).resolve() if start is not None else Path.cwd().resolve()

    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists() or (candidate / ".claude-plugin").exists():
            return candidate

    return current


def _check_path(name: str, path: Path, *, required: bool = True) -> DiagnosticCheck:
    """Check whether a path exists."""

    if path.exists():
        return DiagnosticCheck(name=name, status="OK", message=f"Found {path}")

    status = "FAIL" if required else "WARN"
    return DiagnosticCheck(name=name, status=status, message=f"Missing {path}")


def run_install_diagnostics(project_root: Path) -> tuple[DiagnosticCheck, ...]:
    """Run install/package diagnostics."""

    checks: list[DiagnosticCheck] = []

    checks.append(
        DiagnosticCheck(
            name="python.version",
            status="OK" if sys.version_info >= (3, 10) else "FAIL",
            message=f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
    )

    try:
        pilot_core = importlib.import_module("pilot_core")
        version = str(getattr(pilot_core, "__version__", "unknown"))
        checks.append(
            DiagnosticCheck(
                name="package.import",
                status="OK",
                message=f"pilot_core importable, version={version}",
            )
        )
    except Exception as exc:
        checks.append(
            DiagnosticCheck(
                name="package.import",
                status="FAIL",
                message="pilot_core is not importable",
                detail=repr(exc),
            )
        )

    checks.extend(
        [
            _check_path("project.pyproject", project_root / "pyproject.toml", required=True),
            _check_path(
                "plugin.manifest", project_root / ".claude-plugin" / "plugin.json", required=True
            ),
            _check_path("hooks.manifest", project_root / "hooks" / "hooks.json", required=True),
        ]
    )

    return tuple(checks)


def _read_json(path: Path) -> object:
    """Read JSON from path."""

    return json.loads(path.read_text(encoding="utf-8"))


def run_hook_diagnostics(project_root: Path) -> tuple[DiagnosticCheck, ...]:
    """Run hook manifest and hook script diagnostics."""

    checks: list[DiagnosticCheck] = []
    hooks_dir = project_root / "hooks"
    hooks_json = hooks_dir / "hooks.json"

    checks.append(_check_path("hooks.dir", hooks_dir, required=True))
    checks.append(_check_path("hooks.json", hooks_json, required=True))

    if hooks_json.exists():
        try:
            raw = _read_json(hooks_json)
            checks.append(DiagnosticCheck("hooks.json.parse", "OK", "hooks.json parses as JSON"))

            if isinstance(raw, dict) and "hooks" in raw:
                checks.append(DiagnosticCheck("hooks.json.contract", "OK", "hooks key exists"))
            else:
                checks.append(DiagnosticCheck("hooks.json.contract", "FAIL", "hooks key missing"))
        except Exception as exc:
            checks.append(
                DiagnosticCheck(
                    "hooks.json.parse",
                    "FAIL",
                    "hooks.json could not be parsed",
                    detail=repr(exc),
                )
            )

    for filename in REQUIRED_HOOK_FILES:
        path = hooks_dir / filename
        checks.append(_check_path(f"hook.{filename}", path, required=True))

        if path.exists():
            try:
                py_compile.compile(str(path), doraise=True)
                checks.append(DiagnosticCheck(f"hook.{filename}.syntax", "OK", "Python syntax OK"))
            except Exception as exc:
                checks.append(
                    DiagnosticCheck(
                        f"hook.{filename}.syntax",
                        "FAIL",
                        "Python syntax failed",
                        detail=repr(exc),
                    )
                )

    return tuple(checks)


def _sqlite_tables(conn: sqlite3.Connection) -> set[str]:
    """Return SQLite table names."""

    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {str(row[0]) for row in rows}


def run_db_diagnostics(db_path: Path | None) -> tuple[DiagnosticCheck, ...]:
    """Run DB diagnostics."""

    checks: list[DiagnosticCheck] = []

    if db_path is None:
        candidates = ", ".join(str(path) for path in default_budget_db_candidates())
        return (
            DiagnosticCheck(
                name="db.path",
                status="WARN",
                message="No Pilot DB found yet",
                detail=f"Checked: {candidates}",
            ),
        )

    checks.append(_check_path("db.path", db_path, required=False))

    if not db_path.exists():
        return tuple(checks)

    try:
        conn = sqlite3.connect(db_path)
        try:
            tables = _sqlite_tables(conn)
            checks.append(
                DiagnosticCheck(
                    name="db.connect",
                    status="OK",
                    message=f"Connected to {db_path}",
                )
            )
            checks.append(
                DiagnosticCheck(
                    name="db.tables",
                    status="OK" if tables else "WARN",
                    message=f"Tables: {', '.join(sorted(tables)) if tables else 'none'}",
                )
            )

            for table_name in REQUIRED_DB_TABLES:
                checks.append(
                    DiagnosticCheck(
                        name=f"db.table.{table_name}",
                        status="OK" if table_name in tables else "WARN",
                        message="exists" if table_name in tables else "missing",
                    )
                )

            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()
            journal = str(journal_mode[0]) if journal_mode is not None else "unknown"
            checks.append(
                DiagnosticCheck(
                    name="db.journal_mode",
                    status="OK" if journal.lower() == "wal" else "WARN",
                    message=f"journal_mode={journal}",
                )
            )
        finally:
            conn.close()
    except Exception as exc:
        checks.append(
            DiagnosticCheck(
                name="db.connect",
                status="FAIL",
                message=f"Could not connect to {db_path}",
                detail=repr(exc),
            )
        )

    return tuple(checks)


def run_doctor(
    *,
    project_root: Path | None = None,
    db_path: Path | None = None,
) -> DiagnosticReport:
    """Run all doctor diagnostics."""

    resolved_root = project_root if project_root is not None else discover_project_root()
    resolved_db = db_path if db_path is not None else find_existing_budget_db()

    checks = (
        *run_install_diagnostics(resolved_root),
        *run_hook_diagnostics(resolved_root),
        *run_db_diagnostics(resolved_db),
    )

    return DiagnosticReport(checks=checks)


def diagnostic_report_summary(report: DiagnosticReport) -> dict[str, object]:
    """Return serialisable diagnostic report."""

    return {
        "status": report.status,
        "ok_count": report.ok_count,
        "warning_count": report.warning_count,
        "failed_count": report.failed_count,
        "checks": [
            {
                "name": check.name,
                "status": check.status,
                "message": check.message,
                "detail": check.detail,
            }
            for check in report.checks
        ],
    }


def render_doctor_text(report: DiagnosticReport) -> str:
    """Render doctor report as readable text."""

    lines = [
        "Pilot Doctor",
        "============",
        f"Overall: {report.status}",
        f"OK: {report.ok_count} | WARN: {report.warning_count} | FAIL: {report.failed_count}",
        "",
    ]

    for check in report.checks:
        detail = f" ({check.detail})" if check.detail else ""
        lines.append(f"[{check.status}] {check.name}: {check.message}{detail}")

    return "\n".join(lines)


def build_doctor_arg_parser() -> argparse.ArgumentParser:
    """Build parser for pilot doctor."""

    parser = argparse.ArgumentParser(prog="pilot doctor")
    parser.add_argument("--project-root", default=None, help="Project root to inspect")
    parser.add_argument("--db", default=None, help="Pilot SQLite DB path")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0 even if diagnostics fail",
    )
    return parser


def doctor_main(argv: Sequence[str] | None = None) -> int:
    """Run pilot doctor."""

    parser = build_doctor_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    project_root = Path(args.project_root).resolve() if args.project_root is not None else None
    db_path = Path(os.path.expandvars(os.path.expanduser(args.db))) if args.db is not None else None

    report = run_doctor(project_root=project_root, db_path=db_path)

    if bool(args.json):
        print(json.dumps(diagnostic_report_summary(report), indent=2, sort_keys=True))
    else:
        print(render_doctor_text(report))

    if bool(args.no_fail):
        return 0

    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(doctor_main(sys.argv[1:]))
