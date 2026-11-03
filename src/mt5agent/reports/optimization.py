from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

SS = "{urn:schemas-microsoft-com:office:spreadsheet}"
OFFICE = "{urn:schemas-microsoft-com:office:office}"
METRIC_COLUMNS = frozenset({
    "Pass", "Result", "Profit", "Expected Payoff", "Profit Factor", "Recovery Factor",
    "Sharpe Ratio", "Custom", "Equity DD %", "Trades", "Forward Result", "Back Result",
})


@dataclass
class OptimizationResult:
    title: str
    columns: list[str]
    passes: list[dict]
    params: list[str]

    def best(self, by: str = "Profit Factor", min_trades: int = 0) -> dict:
        eligible = [p for p in self.passes if (p.get("Trades") or 0) >= min_trades]
        if not eligible:
            raise ValueError(f"No pass with at least {min_trades} trades")
        return max(eligible, key=lambda p: p.get(by) or float("-inf"))

    def top(self, n: int = 10, by: str = "Result") -> list[dict]:
        return sorted(self.passes, key=lambda p: p.get(by) or 0, reverse=True)[:n]

    @property
    def profitable(self) -> int:
        return sum(1 for p in self.passes if (p.get("Profit") or 0) > 0)

    def to_dataframe(self):
        import pandas as pd

        return pd.DataFrame(self.passes)


def parse_optimization_xml(data: bytes | str) -> OptimizationResult:
    root = ET.fromstring(data.encode() if isinstance(data, str) else data)
    rows = [_cells(row) for row in root.iter(f"{SS}Row")]
    if not rows:
        return OptimizationResult("", [], [], [])

    columns = [str(c) for c in rows[0]]
    params = [c for c in columns if c not in METRIC_COLUMNS]
    passes = [_normalize(dict(zip(columns, row)), ("Pass", "Trades", *params)) for row in rows[1:]]
    title = root.find(f".//{OFFICE}Title")
    return OptimizationResult(title.text if title is not None else "", columns, passes, params)


def _cells(row: ET.Element) -> list:
    values = []
    for cell in row.iter(f"{SS}Cell"):
        data = cell.find(f"{SS}Data")
        if data is None:
            values.append(None)
        elif data.get(f"{SS}Type") == "Number":
            values.append(float(data.text))
        else:
            values.append(data.text)
    return values


def _normalize(record: dict, integer_keys: tuple[str, ...]) -> dict:
    for key in integer_keys:
        value = record.get(key)
        if isinstance(value, float) and value.is_integer():
            record[key] = int(value)
    return record
