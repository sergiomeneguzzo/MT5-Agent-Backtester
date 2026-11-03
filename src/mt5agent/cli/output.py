from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Sequence
from typing import Any

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


class Output:
    def __init__(self, as_json: bool = False, color: bool | None = None):
        self.as_json = as_json
        self.color = (sys.stdout.isatty() and not as_json) if color is None else color

    def json(self, data: Any) -> None:
        print(json.dumps(data, indent=2, default=str))

    def line(self, text: str = "", style: str = "") -> None:
        print(self.paint(text, style))

    def paint(self, text: str, style: str) -> str:
        return f"{style}{text}{RESET}" if self.color and style else text

    def signed(self, value: float, text: str | None = None) -> str:
        return self.paint(text or f"{value:+.2f}", GREEN if value >= 0 else RED)

    def table(self, header: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
        cells = [list(map(str, header))] + [["" if v is None else str(v) for v in row] for row in rows]
        widths = [max(_visible_len(row[i]) for row in cells) for i in range(len(header))]
        for n, row in enumerate(cells):
            print("  ".join(_pad(value, width, left=i == 0) for i, (value, width) in enumerate(zip(row, widths))))
            if n == 0:
                print("  ".join("─" * w for w in widths))

    def pairs(self, data: dict, header: tuple[str, str] = ("field", "value")) -> None:
        self.table(header, data.items())


def _visible_len(text: str) -> int:
    for code in (GREEN, RED, DIM, BOLD, RESET):
        text = text.replace(code, "")
    return len(text)


def _pad(text: str, width: int, left: bool) -> str:
    padding = " " * (width - _visible_len(text))
    return text + padding if left else padding + text
