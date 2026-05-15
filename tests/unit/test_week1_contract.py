from __future__ import annotations

from scripts.verify_week1 import verify_week1


def test_week1_contracts_are_valid() -> None:
    assert verify_week1() == []
