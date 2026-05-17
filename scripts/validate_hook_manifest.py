"""Validate Pilot's Claude plugin and hook manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

PLUGIN_MANIFEST_PATH = ROOT / ".claude-plugin" / "plugin.json"
HOOK_MANIFEST_PATH = ROOT / "hooks" / "hooks.json"

EXPECTED_HOOK_EVENTS = {
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Stop",
    "SessionEnd",
}

TOOL_HOOK_EVENTS = {
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)

    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object.")

    return payload


def _first_hook_command_config(hooks_manifest: dict[str, Any], event: str) -> dict[str, Any]:
    event_entries = hooks_manifest["hooks"][event]
    if not isinstance(event_entries, list) or not event_entries:
        raise ValueError(f"{event} must have at least one registration entry.")

    command_entries = event_entries[0].get("hooks")
    if not isinstance(command_entries, list) or not command_entries:
        raise ValueError(f"{event} must have at least one command hook.")

    command_config = command_entries[0]
    if not isinstance(command_config, dict):
        raise TypeError(f"{event} command hook must be a JSON object.")

    return command_config


def _command_target_exists(command: str) -> bool:
    marker = "${CLAUDE_PLUGIN_ROOT}/"
    if marker not in command:
        return False

    relative_path = command.split(marker, maxsplit=1)[1].strip()
    return (ROOT / relative_path).exists()


def validate_plugin_manifest() -> list[str]:
    errors: list[str] = []
    manifest = _read_json(PLUGIN_MANIFEST_PATH)

    required_fields = {
        "name",
        "version",
        "description",
        "author",
        "homepage",
        "keywords",
        "license",
    }

    missing_fields = required_fields - set(manifest)
    if missing_fields:
        errors.append(f"plugin.json missing fields: {sorted(missing_fields)}")

    if manifest.get("name") != "pilot":
        errors.append("plugin.json name must be 'pilot'.")

    if manifest.get("license") != "MIT":
        errors.append("plugin.json license must be 'MIT'.")

    keywords = manifest.get("keywords")
    if not isinstance(keywords, list) or "claude-code" not in keywords:
        errors.append("plugin.json keywords must include 'claude-code'.")

    return errors


def validate_hook_manifest() -> list[str]:
    errors: list[str] = []
    manifest = _read_json(HOOK_MANIFEST_PATH)

    hooks = manifest.get("hooks")
    if not isinstance(hooks, dict):
        return ["hooks.json must contain a top-level 'hooks' object."]

    registered_events = set(hooks)
    if registered_events != EXPECTED_HOOK_EVENTS:
        errors.append(
            "hooks.json registered events mismatch: "
            f"expected={sorted(EXPECTED_HOOK_EVENTS)} actual={sorted(registered_events)}"
        )

    for event in sorted(EXPECTED_HOOK_EVENTS & registered_events):
        command_config = _first_hook_command_config(manifest, event)

        if command_config.get("type") != "command":
            errors.append(f"{event} hook type must be 'command'.")

        command = command_config.get("command")
        if not isinstance(command, str) or not command.startswith("python "):
            errors.append(f"{event} command must start with 'python '.")

        if isinstance(command, str) and not _command_target_exists(command):
            errors.append(f"{event} command target does not exist: {command}")

        timeout = command_config.get("timeout")
        if not isinstance(timeout, int) or not 1 <= timeout <= 10:
            errors.append(f"{event} timeout must be an integer between 1 and 10.")

        event_entry = manifest["hooks"][event][0]
        if event in TOOL_HOOK_EVENTS and event_entry.get("matcher") != ".*":
            errors.append(f"{event} must include matcher='.*'.")

    pre_tool = _first_hook_command_config(manifest, "PreToolUse")
    if pre_tool.get("async") is True:
        errors.append("PreToolUse must not be async because it can affect permission flow.")

    for event in ("UserPromptSubmit", "PostToolUse", "PostToolUseFailure"):
        command_config = _first_hook_command_config(manifest, event)
        if command_config.get("async") is not True:
            errors.append(f"{event} should be async to avoid user-facing latency.")

    return errors


def main() -> int:
    errors = validate_plugin_manifest() + validate_hook_manifest()

    if errors:
        print("Pilot hook manifest validation failed:")
        for error in errors:
            print(f" - {error}")
        return 1

    print("Pilot hook manifest validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
