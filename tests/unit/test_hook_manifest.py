from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pilot_core.constants import HookEvent

ROOT = Path(__file__).resolve().parents[2]

PLUGIN_MANIFEST_PATH = ROOT / ".claude-plugin" / "plugin.json"
HOOK_MANIFEST_PATH = ROOT / "hooks" / "hooks.json"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)

    assert isinstance(payload, dict)
    return payload


def _first_hook_command_config(hooks_manifest: dict[str, Any], event: str) -> dict[str, Any]:
    event_entries = hooks_manifest["hooks"][event]
    assert isinstance(event_entries, list)
    assert event_entries

    command_entries = event_entries[0]["hooks"]
    assert isinstance(command_entries, list)
    assert command_entries

    command_config = command_entries[0]
    assert isinstance(command_config, dict)

    return command_config


def test_plugin_manifest_has_required_metadata() -> None:
    manifest = _read_json(PLUGIN_MANIFEST_PATH)

    assert manifest["name"] == "pilot"
    assert manifest["version"] == "0.1.0"
    assert "Claude Code" in manifest["description"]
    assert manifest["homepage"] == "https://github.com/AlirezaYegane/pilot"
    assert "claude-code" in manifest["keywords"]
    assert manifest["license"] == "MIT"


def test_hooks_manifest_registers_all_supported_events() -> None:
    manifest = _read_json(HOOK_MANIFEST_PATH)
    expected_events = {event.value for event in HookEvent}

    assert set(manifest["hooks"]) == expected_events


def test_all_hook_commands_point_to_existing_scripts() -> None:
    manifest = _read_json(HOOK_MANIFEST_PATH)

    for event in HookEvent:
        command_config = _first_hook_command_config(manifest, event.value)
        command = command_config["command"]

        assert command_config["type"] == "command"
        assert command.startswith("python ")

        marker = "${CLAUDE_PLUGIN_ROOT}/"
        assert marker in command

        relative_script_path = command.split(marker, maxsplit=1)[1]
        assert (ROOT / relative_script_path).exists()


def test_tool_hooks_use_global_matcher() -> None:
    manifest = _read_json(HOOK_MANIFEST_PATH)

    for event in (
        HookEvent.PRE_TOOL_USE,
        HookEvent.POST_TOOL_USE,
        HookEvent.POST_TOOL_USE_FAILURE,
    ):
        assert manifest["hooks"][event.value][0]["matcher"] == ".*"


def test_pre_tool_use_is_not_async() -> None:
    manifest = _read_json(HOOK_MANIFEST_PATH)

    command_config = _first_hook_command_config(manifest, HookEvent.PRE_TOOL_USE.value)

    assert command_config.get("async") is None


def test_post_hooks_are_async_to_reduce_user_facing_latency() -> None:
    manifest = _read_json(HOOK_MANIFEST_PATH)

    for event in (
        HookEvent.USER_PROMPT_SUBMIT,
        HookEvent.POST_TOOL_USE,
        HookEvent.POST_TOOL_USE_FAILURE,
    ):
        command_config = _first_hook_command_config(manifest, event.value)
        assert command_config["async"] is True


def test_hook_timeouts_are_bounded() -> None:
    manifest = _read_json(HOOK_MANIFEST_PATH)

    for event in HookEvent:
        command_config = _first_hook_command_config(manifest, event.value)
        timeout = command_config["timeout"]

        assert isinstance(timeout, int)
        assert 1 <= timeout <= 10
