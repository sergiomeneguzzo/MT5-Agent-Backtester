"""Walk-forward fold generation and result aggregation."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .metrics import summarize


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    return date(d.year + y, m + 1, min(d.day, 28))


@dataclass(frozen=True)
class Fold:
    index: int
    is_start: date
    is_end: date
    oos_start: date
    oos_end: date

    def label(self) -> str:
        return f"#{self.index}  IS {self.is_start}..{self.is_end}  OOS {self.oos_start}..{self.oos_end}"


def make_folds(start: date, end: date, is_months: int, oos_months: int,
               anchored: bool = False) -> list[Fold]:
    """Rolling (or anchored) in-sample / out-of-sample windows.

    Each OOS window starts where its IS window ends; the next fold moves forward
    by ``oos_months`` so that the OOS windows tile the period without overlap.
    """
    if is_months <= 0 or oos_months <= 0:
        raise ValueError("is_months and oos_months must be positive")
    folds: list[Fold] = []
    i = 0
    while True:
        is_start = start if anchored else add_months(start, i * oos_months)
        is_end = add_months(start, is_months + i * oos_months)
        if is_end >= end:
            break
        oos_end = min(add_months(is_end, oos_months), end)
        folds.append(Fold(i + 1, is_start, is_end, is_end, oos_end))
        if oos_end >= end:
            break
        i += 1
    return folds


@dataclass
class FoldResult:
    fold: Fold
    best_params: dict
    is_metrics: dict
    oos_summary: dict
    oos_trades: list = field(default_factory=list)


@dataclass
class WalkForwardResult:
    folds: list[FoldResult]
    initial_deposit: float
    criterion: str

    @property
    def oos_trades(self) -> list:
        return [t for f in self.folds for t in f.oos_trades]

    def summary(self) -> dict:
        s = summarize(self.oos_trades, self.initial_deposit)
        s["folds"] = len(self.folds)
        s["profitable_folds"] = sum(1 for f in self.folds if f.oos_summary.get("net_profit", 0) > 0)
        s["efficiency"] = self.efficiency()
        return s

    def efficiency(self) -> float | None:
        """Walk-forward efficiency: OOS profit per month / IS profit per month."""
        is_rate = oos_rate = 0.0
        for f in self.folds:
            is_m = max(1, _months(f.fold.is_start, f.fold.is_end))
            oos_m = max(1, _months(f.fold.oos_start, f.fold.oos_end))
            is_rate += (f.is_metrics.get("Profit") or 0.0) / is_m
            oos_rate += f.oos_summary.get("net_profit", 0.0) / oos_m
        if is_rate <= 0:
            return None
        return round(oos_rate / is_rate, 3)


def _months(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month
