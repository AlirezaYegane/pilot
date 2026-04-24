from __future__ import annotations

from pilot_core import __version__


def test_version_is_defined() -> None:
    assert __version__ == "0.1.0"
