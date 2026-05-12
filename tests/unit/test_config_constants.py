from __future__ import annotations

from pilot_core.config import load_config
from pilot_core.constants import ActivationMode, parse_activation_mode


def test_config_default_activation_mode_is_known_constant() -> None:
    config = load_config()
    mode = parse_activation_mode(config.signals.default_activation_mode)
    assert mode in ActivationMode
