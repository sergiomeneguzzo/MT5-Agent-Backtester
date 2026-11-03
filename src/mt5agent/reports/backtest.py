from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime

from ..metrics import summarize, yearly_returns
from ._xlsx import Row, read_rows

TIME_FORMAT = "%Y.%m.%d %H:%M:%S"
SECTIONS = ("Settings", "Results", "Orders", "Deals")
PRIVATE_FIELDS = ("server", "company", "account", "login", "name")
DEAL_COLUMNS = ("time", "deal", "symbol", "type", "direction", "volume", "price", "order",
                "commission", "swap", "profit", "balance", "comment")


@dataclass
class Deal:
    time: datetime
    deal: int
    symbol: str
    type: str
    direction: str
    volume: float
    price: float
    order: int
    commission: float
    swap: float
    profit: float
    balance: float
    comment: str = ""

    @property
    def net(self) -> float:
        return self.profit + self.commission + self.swap


@dataclass
class Trade:
    close_time: datetime
    symbol: str
    side: str
    volume: float
    price: float
    net: float
    balance: float


@dataclass
class BacktestReport:
    expert: str = ""
    symbol: str = ""
    period: str = ""
    inputs: dict[str, str] = field(default_factory=dict)
    settings: dict[str, str] = field(default_factory=dict)
    results: dict[str, str] = field(default_factory=dict)
    deals: list[Deal] = field(default_factory=list)

    @property
    def initial_deposit(self) -> float:
        first_balance = next((d.balance for d in self.deals if d.type == "balance"), None)
        return first_balance if first_balance is not None else (to_number(self.settings.get("initial deposit")) or 0.0)

    @property
    def trades(self) -> list[Trade]:
        trades, entry_costs = [], 0.0
        for deal in self.deals:
            if deal.type not in ("buy", "sell"):
                continue
            if deal.direction == "in":
                entry_costs += deal.commission + deal.swap
                continue
            side = "long" if deal.type == "sell" else "short"
            trades.append(Trade(deal.time, deal.symbol, side, deal.volume, deal.price,
                                deal.net + entry_costs, deal.balance))
            entry_costs = 0.0
        return trades

    def equity_curve(self) -> list[tuple[datetime, float]]:
        return [(d.time, d.balance) for d in self.deals if d.direction != "in" or d.type == "balance"]

    def metric(self, label: str) -> float | None:
        return to_number(self.results.get(label.lower().rstrip(":")))

    def summary(self) -> dict:
        return summarize(self.trades, self.initial_deposit)

    def yearly_returns(self) -> dict[int, float]:
        return yearly_returns(self.trades, self.initial_deposit)

    def to_dataframe(self):
        import pandas as pd

        return pd.DataFrame([asdict(d) for d in self.deals])


def parse_backtest_xlsx(data: bytes, *, keep_private: bool = False) -> BacktestReport:
    report = BacktestReport()
    section, deals_header_seen, last_label = "", False, ""

    for row in read_rows(data):
        filled = [c for c in row if c not in (None, "")]
        if not filled:
            continue
        if len(filled) == 1 and row[0] in SECTIONS:
            section, deals_header_seen = row[0], False
            continue

        if section in ("Settings", "Results"):
            target = report.settings if section == "Settings" else report.results
            for label, value in _label_pairs(row, continues_inputs=last_label == "inputs"):
                last_label = label
                if label == "inputs" and "=" in value:
                    name, val = value.split("=", 1)
                    report.inputs[name] = val
                else:
                    target[label] = value
        elif section == "Deals":
            if not deals_header_seen:
                deals_header_seen = True
            elif _parse_time(row[0]):
                report.deals.append(_deal(row))
        elif not section and row[0] != "Strategy Tester Report":
            report.settings.setdefault("server", row[0])

    report.expert = report.settings.get("expert", "")
    report.symbol = report.settings.get("symbol", "")
    report.period = report.settings.get("period", "")
    if not keep_private:
        for key in PRIVATE_FIELDS:
            report.settings.pop(key, None)
    return report


def to_number(value: str | None) -> float | None:
    if not value:
        return None
    match = re.match(r"^-?\d+(\.\d+)?", value.replace(" ", "").replace(" ", "").rstrip("%"))
    return float(match.group()) if match else None


def _parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.strptime(value, TIME_FORMAT) if value else None
    except ValueError:
        return None


def _label_pairs(row: Row, continues_inputs: bool) -> list[tuple[str, str]]:
    pairs, i = [], 0
    while i < len(row):
        cell = row[i]
        if isinstance(cell, str) and cell.endswith(":"):
            j = i + 1
            while j < len(row) and row[j] in (None, ""):
                j += 1
            if j < len(row):
                pairs.append((cell[:-1].strip().lower(), row[j]))
            i = j + 1
            continue
        if i == 3 and cell and continues_inputs:
            pairs.append(("inputs", cell))
        i += 1
    return pairs


def _deal(row: Row) -> Deal:
    values = dict(zip(DEAL_COLUMNS, row))
    number = lambda key: to_number(values.get(key)) or 0.0
    return Deal(
        time=_parse_time(values["time"]),
        deal=int(number("deal")),
        symbol=values.get("symbol") or "",
        type=values.get("type") or "",
        direction=values.get("direction") or "",
        volume=number("volume"),
        price=number("price"),
        order=int(number("order")),
        commission=number("commission"),
        swap=number("swap"),
        profit=number("profit"),
        balance=number("balance"),
        comment=values.get("comment") or "",
    )
