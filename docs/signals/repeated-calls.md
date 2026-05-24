# Repeated Calls Signal

The repeated-calls signal detects short-window tool loops.

## Detection rule

Pilot fingerprints each tool call as:

```text
(tool_name, sha256(normalised_tool_input))
Then it counts repeated fingerprints in the recent tool-call window.

Default window:

last 10 tool calls

Default threshold:

repeat_count >= 3
Why this matters

Repeated identical tool calls often indicate that the agent is stuck in a loop.
This can burn context, tokens, and rate limits without producing useful work.

Normalisation

Tool inputs are normalised before hashing:

dictionary keys are sorted recursively
list order is preserved
strings are stripped
payloads are serialised as compact JSON

This prevents false negatives caused by harmless key-order or whitespace changes.

Score shape
0 or 1 repeat  -> 0.00
2 repeats      -> 0.35
3 repeats      -> 0.65
4 repeats      -> 0.80
5+ repeats     -> approaches 1.00
Current status

Day 23 implements the pure signal logic and fixture coverage.
Future days will integrate this into the full signal registry and decision engine.
