from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Range:
    start: float
    stop: float
    step: float

    def __post_init__(self) -> None:
        if self.step <= 0:
            raise ValueError("step must be > 0")
        if self.stop < self.start:
            raise ValueError("stop must be >= start")

    def values(self) -> list[float]:
        values, current = [], self.start
        while current <= self.stop + 1e-12:
            values.append(round(current, 10))
            current += self.step
        return values

    @classmethod
    def parse(cls, value: Any) -> Range | Any:
        if isinstance(value, (list, tuple)) and len(value) == 3:
            return cls(*value)
        if isinstance(value, Mapping) and {"start", "stop", "step"} <= value.keys():
            return cls(value["start"], value["stop"], value["step"])
        return value


def to_set_lines(inputs: Mapping[str, Any] | None) -> list[str]:
    lines = []
    for name, value in (inputs or {}).items():
        if isinstance(value, Range):
            start, step, stop = (_format(v) for v in (value.start, value.step, value.stop))
            lines.append(f"{name}={start}||{start}||{step}||{stop}||Y")
        else:
            lines.append(f"{name}={_format(value)}")
    return lines


def grid_size(inputs: Mapping[str, Any] | None) -> int:
    size = 1
    for value in (inputs or {}).values():
        if isinstance(value, Range):
            size *= len(value.values())
    return size


def parse_inputs(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    return {name: Range.parse(value) for name, value in (raw or {}).items()}


def parse_assignments(items: Iterable[str]) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    for item in items:
        name, sep, value = item.partition("=")
        if not sep:
            raise ValueError(f"bad parameter {item!r}: expected Name=value or Name=start:stop:step")
        parts = value.split(":")
        inputs[name] = Range(*map(float, parts)) if len(parts) == 3 else _literal(value)
    return inputs


def _format(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _literal(text: str) -> Any:
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text
