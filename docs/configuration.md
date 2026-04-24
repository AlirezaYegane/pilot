# Pilot Configuration

Pilot uses a simple precedence model:

1. Built-in defaults
2. YAML config file
3. Environment variables

Default config path:

```text
~/.claude/plugins/pilot/config.yaml
```

## Example

```yaml
quiet: false

storage:
  data_dir: ~/.claude/plugins/pilot/data
  debug_log_path: ~/.claude/plugins/pilot/debug.log
  handoff_dir_name: handoffs

signals:
  token_burn_ratio: 2.0
  repeated_call_count: 3
  error_cascade_rate: 0.4
  backtracking_count: 2
  context_saturation_ratio: 0.8
  self_doubt_marker_count: 3
  rate_limit_eta_minutes: 20
  low_productivity_ratio: 0.5
  default_activation_mode: shadow
  warn_after_turn: 5
  warning_cooldown_turns: 3

budget:
  plan: max5
  weekly_token_cap: 250000000
  warning_usage_ratio: 0.8

context:
  default_context_limit: 200000
  system_prompt_token_offset: 20000
```

## Useful environment overrides

```powershell
$env:PILOT_CONFIG="C:\path\to\pilot.yaml"
$env:PILOT_QUIET="true"
$env:PILOT_DATA_DIR="D:\pilot-data"
$env:PILOT_TOKEN_BURN_RATIO="3.0"
$env:PILOT_DEFAULT_ACTIVATION_MODE="warn"
$env:PILOT_CONTEXT_LIMIT="1000000"
```

## CLI

```powershell
pilot config-path
pilot show-config
pilot doctor
```
