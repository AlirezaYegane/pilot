# Pilot Project Structure

This document freezes the Week 1 project structure.

## Core principles

Pilot follows these product-level constraints:

- Zero-configuration by default
- Zero-overhead in hook paths
- Never break the user's session
- Local-first runtime state
- Small, testable modules

## Current top-level structure

```text
pilot/
├─ .claude-plugin/
├─ hooks/
├─ skills/
├─ agents/
├─ pilot_core/
├─ tests/
├─ scripts/
├─ docs/
├─ README.md
├─ LICENSE
├─ pyproject.toml
├─ .editorconfig
└─ .gitignore
Python package structure
pilot_core/
├─ __init__.py
├─ cli.py
├─ config.py
├─ constants.py
├─ paths.py
├─ safety.py
├─ models.py
├─ hashing.py
├─ tokenizer.py
├─ storage.py
├─ budget.py
├─ state_machine.py
├─ decision_engine.py
├─ warnings.py
├─ handoff.py
├─ replay.py
├─ signals/
└─ render/
Freeze rules
Do not rename public enum values without a migration.
Do not scatter runtime paths outside pilot_core/paths.py.
Do not implement hook-specific silent-failure logic outside pilot_core/safety.py.
Do not add raw state/signal strings when constants already exist.
Do not add database code until the schema is documented.
Do not make pre-hooks heavy.
Week 2 entry point

Week 2 starts with storage:

Define SQLite schema.
Create sessions and turns tables.
Add migrations.
Enable WAL and busy timeout.
Add repository APIs and tests.
