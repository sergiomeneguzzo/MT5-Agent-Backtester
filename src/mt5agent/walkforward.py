from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .metrics import summarize


@dataclass(frozen=True)
class Fold:
    index: int
    is_start: date
    is_end: date
    oos_start: date
    oos_end: date

    def label(self) -> str:
        return f"#{self.index}  IS {self.is_start}..{self.is_end}  OOS {self.oos_start}..{self.oos_end}"


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
        return [trade for fold in self.folds for trade in fold.oos_trades]

    def summary(self) -> dict:
        return {
            **summarize(self.oos_trades, self.initial_deposit),
            "folds": len(self.folds),
            "profitable_folds": sum(f.oos_summary.get("net_profit", 0) > 0 for f in self.folds),
            "efficiency": self.efficiency(),
        }

    def efficiency(self) -> float | None:
        is_rate = sum((f.is_metrics.get("Profit") or 0.0) / _months(f.fold.is_start, f.fold.is_end)
                      for f in self.folds)
        oos_rate = sum(f.oos_summary.get("net_profit", 0.0) / _months(f.fold.oos_start, f.fold.oos_end)
                       for f in self.folds)
        return round(oos_rate / is_rate, 3) if is_rate > 0 else None


def make_folds(start: date, end: date, is_months: int, oos_months: int, anchored: bool = False) -> list[Fold]:
    if is_months <= 0 or oos_months <= 0:
        raise ValueError("is_months and oos_months must be positive")
    folds = []
    while True:
        step = len(folds) * oos_months
        is_start = start if anchored else add_months(start, step)
        is_end = add_months(start, is_months + step)
        if is_end >= end:
            break
        oos_end = min(add_months(is_end, oos_months), end)
        folds.append(Fold(len(folds) + 1, is_start, is_end, is_end, oos_end))
        if oos_end >= end:
            break
    return folds


def add_months(day: date, months: int) -> date:
    years, month = divmod(day.month - 1 + months, 12)
    return date(day.year + years, month + 1, min(day.day, 28))


def _months(start: date, end: date) -> int:
    return max(1, (end.year - start.year) * 12 + end.month - start.month)
