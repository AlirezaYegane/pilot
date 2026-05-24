# Signal Base Contract

Day 22 introduces the shared contract for all Pilot degradation signals.

## Files

```text
pilot_core/signals/base.py
tests/unit/test_signal_base.py
Purpose

Every signal detector should return the same structured payload:

name
score
confidence
severity
activation_mode
explanation
evidence
metadata
Design rules
Scores are normalised into the 0.0 .. 1.0 range.
Confidence is also normalised into the 0.0 .. 1.0 range.
Explanations must be human-readable.
Evidence should stay compact and serialisable.
Signal implementations should be deterministic and cheap to run.
Shadow mode means the signal is measured but should not drive user-facing action.
Main types
SignalEvaluationContext
SignalEvidence
SignalResult
SignalDetector
Helper functions
clamp_unit_interval
score_to_severity
confidence_from_observations
build_signal_result
no_signal_result
Next step

Day 23 will implement the first real signal: repeated tool call detection.
