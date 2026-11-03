"""Expert Advisor inputs -> native MT5 ``.set`` lines.

    {"MovingPeriod": 12}                       -> "MovingPeriod=12"
    {"MovingPeriod": Range(10, 100, 10)}       -> "MovingPeriod=10||10||10||100||Y"
    {"UseFilter": True}                        -> "UseFilter=true"
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Range:
    """An input to optimize: ``start``..``stop`` (inclusive) every ``step``."""
    start: float
    stop: float
    step: float

    def __post_init__(self) -> None:
        if self.step <= 0:
            raise ValueError("step must be > 0")
        if self.stop < self.start:
            raise ValueError("stop must be >= start")

    def values(self) -> list[float]:
        out, v = [], self.start
        while v <= self.stop + 1e-12:
            out.append(round(v, 10))
            v += self.step
        return out


def fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def to_set_lines(inputs: Mapping[str, Any] | None) -> list[str]:
    lines = []
    for name, value in (inputs or {}).items():
        if isinstance(value, Range):
            lines.append(f"{name}={fmt(value.start)}||{fmt(value.start)}||{fmt(value.step)}"
                         f"||{fmt(value.stop)}||Y")
        else:
            lines.append(f"{name}={fmt(value)}")
    return lines


def grid_size(inputs: Mapping[str, Any] | None) -> int:
    n = 1
    for value in (inputs or {}).values():
        if isinstance(value, Range):
            n *= len(value.values())
    return n
