"""Parsers for the files the MetaTrader 5 Strategy Tester produces.

* Backtest report  -> ``.xlsx`` (what ``tester_get_report(file_format="xml")``
  writes for a single run). Contains settings, results, every order and every
  deal with the running balance.
* Optimization     -> SpreadsheetML ``.xml``: one row per pass, with the metrics
  and the value of every optimized input.

Standard library only (zipfile + ElementTree), so agents can use it anywhere.
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_SS_NS = "{urn:schemas-microsoft-com:office:spreadsheet}"
_TIME_FMT = "%Y.%m.%d %H:%M:%S"

#: Header fields that identify the broker/account. Dropped unless asked for.
PRIVATE_SETTINGS = ("server", "company", "account", "login", "name")


def _num(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    text = value.replace(" ", "").replace(" ", "").rstrip("%")
    m = re.match(r"^-?\d+(\.\d+)?", text)
    return float(m.group()) if m else None


def _time(value: str | None) -> datetime | None:
    try:
        return datetime.strptime(value, _TIME_FMT) if value else None
    except ValueError:
        return None


@dataclass
class Deal:
    time: datetime
    deal: int
    symbol: str
    type: str          # buy / sell / balance
    direction: str     # in / out / inout / ""
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
    """A closed position, rebuilt from its exit deal (net of commission + swap)."""
    close_time: datetime
    symbol: str
    side: str          # long / short
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

    # -- derived views ----------------------------------------------------
    @property
    def initial_deposit(self) -> float:
        for d in self.deals:
            if d.type == "balance":
                return d.balance
        return _num(self.settings.get("initial deposit")) or 0.0

    @property
    def trades(self) -> list[Trade]:
        """Closed positions. Commission of the entry deal is added to the exit."""
        out: list[Trade] = []
        pending_fees = 0.0
        for d in self.deals:
            if d.type not in ("buy", "sell"):
                continue
            if d.direction == "in":
                pending_fees += d.commission + d.swap
                continue
            side = "long" if d.type == "sell" else "short"   # exit deal is opposite
            out.append(Trade(d.time, d.symbol, side, d.volume, d.price,
                             d.net + pending_fees, d.balance))
            pending_fees = 0.0
        return out

    def equity_curve(self) -> list[tuple[datetime, float]]:
        """Balance after every deal that changed it."""
        return [(d.time, d.balance) for d in self.deals if d.direction != "in" or d.type == "balance"]

    def metric(self, label: str) -> float | None:
        """Numeric value of a 'Results' line, e.g. ``metric("Profit Factor")``."""
        return _num(self.results.get(label.lower().rstrip(":")))

    def summary(self) -> dict:
        from .metrics import summarize
        return summarize(self.trades, self.initial_deposit)

    def to_dataframe(self):
        """Deals as a pandas DataFrame (requires the ``plot`` extra)."""
        import pandas as pd
        return pd.DataFrame([d.__dict__ for d in self.deals])


# ---------------------------------------------------------------------------
# xlsx (backtest)
# ---------------------------------------------------------------------------
def _xml(zf: zipfile.ZipFile, name: str) -> ET.Element:
    # MT5 writes some parts as UTF-16; ElementTree honours the BOM/declaration.
    return ET.fromstring(zf.read(name))


def _xlsx_rows(data: bytes) -> list[list[str | None]]:
    zf = zipfile.ZipFile(io.BytesIO(data))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in zf.namelist():
        for si in _xml(zf, "xl/sharedStrings.xml").iter(f"{_XLSX_NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{_XLSX_NS}t")))
    sheet = _xml(zf, "xl/worksheets/sheet1.xml")
    rows: list[list[str | None]] = []
    for row in sheet.iter(f"{_XLSX_NS}row"):
        cells: dict[int, str | None] = {}
        for c in row.iter(f"{_XLSX_NS}c"):
            col = 0
            for ch in re.match(r"[A-Z]+", c.get("r", "A")).group():
                col = col * 26 + ord(ch) - 64
            v, inline = c.find(f"{_XLSX_NS}v"), c.find(f"{_XLSX_NS}is")
            if v is not None and v.text is not None:
                cells[col - 1] = shared[int(v.text)] if c.get("t") == "s" else v.text
            elif inline is not None:
                cells[col - 1] = "".join(t.text or "" for t in inline.iter(f"{_XLSX_NS}t"))
        width = max(cells) + 1 if cells else 0
        rows.append([cells.get(i) for i in range(width)])
    return rows


def parse_backtest_xlsx(data: bytes, *, keep_private: bool = False) -> BacktestReport:
    """Parse the ``.xlsx`` report of a single Strategy Tester run."""
    rows = _xlsx_rows(data)
    rep = BacktestReport()
    section, last_key, header = "", "", None

    for row in rows:
        cells = [c for c in row if c not in (None, "")]
        if not cells:
            continue
        first = row[0] if row else None
        if first in ("Settings", "Results", "Orders", "Deals") and len(cells) == 1:
            section, header = first, None
            continue
        if section in ("Settings", "Results"):
            # label/value pairs laid out as  label, -, -, value, label, -, -, -, value ...
            pairs: list[tuple[str, str]] = []
            i = 0
            while i < len(row):
                cell = row[i]
                if isinstance(cell, str) and cell.endswith(":"):
                    j = i + 1
                    while j < len(row) and row[j] in (None, ""):
                        j += 1
                    if j < len(row):
                        pairs.append((cell[:-1].strip().lower(), row[j]))
                    i = j + 1
                else:
                    if i == 3 and cell and section == "Settings" and last_key == "inputs":
                        pairs.append(("inputs", cell))   # continuation line of Inputs
                    i += 1
            for key, value in pairs:
                last_key = key
                target = rep.settings if section == "Settings" else rep.results
                if key == "inputs" and "=" in value:
                    name, val = value.split("=", 1)
                    rep.inputs[name] = val
                else:
                    target[key] = value
        elif section == "Deals":
            if header is None:
                header = row
                continue
            if _time(row[0]) is None:
                continue                      # totals line
            g = lambda i, r=row: r[i] if i < len(r) else None
            rep.deals.append(Deal(
                time=_time(g(0)), deal=int(_num(g(1)) or 0), symbol=g(2) or "",
                type=g(3) or "", direction=g(4) or "", volume=_num(g(5)) or 0.0,
                price=_num(g(6)) or 0.0, order=int(_num(g(7)) or 0),
                commission=_num(g(8)) or 0.0, swap=_num(g(9)) or 0.0,
                profit=_num(g(10)) or 0.0, balance=_num(g(11)) or 0.0, comment=g(12) or "",
            ))
        elif section == "" and first and first != "Strategy Tester Report" and "server" not in rep.settings:
            rep.settings["server"] = first     # line 2: "<server> (Build NNNN)"

    rep.expert = rep.settings.get("expert", "")
    rep.symbol = rep.settings.get("symbol", "")
    rep.period = rep.settings.get("period", "")
    if not keep_private:
        for key in PRIVATE_SETTINGS:
            rep.settings.pop(key, None)
    return rep


# ---------------------------------------------------------------------------
# SpreadsheetML (optimization)
# ---------------------------------------------------------------------------
@dataclass
class OptimizationResult:
    title: str
    columns: list[str]
    passes: list[dict]
    params: list[str]

    def best(self, by: str = "Profit Factor", min_trades: int = 0) -> dict:
        ok = [p for p in self.passes if (p.get("Trades") or 0) >= min_trades]
        if not ok:
            raise ValueError(f"No pass with at least {min_trades} trades")
        return max(ok, key=lambda p: p.get(by) or float("-inf"))

    def to_dataframe(self):
        import pandas as pd
        return pd.DataFrame(self.passes)


_METRIC_COLUMNS = {"Pass", "Result", "Profit", "Expected Payoff", "Profit Factor",
                   "Recovery Factor", "Sharpe Ratio", "Custom", "Equity DD %", "Trades",
                   "Forward Result", "Back Result"}


def parse_optimization_xml(data: bytes | str) -> OptimizationResult:
    root = ET.fromstring(data if isinstance(data, bytes) else data.encode())
    title_el = root.find(".//{urn:schemas-microsoft-com:office:office}Title")
    rows = root.iter(f"{_SS_NS}Row")
    columns: list[str] = []
    passes: list[dict] = []
    for i, row in enumerate(rows):
        values = []
        for cell in row.iter(f"{_SS_NS}Cell"):
            d = cell.find(f"{_SS_NS}Data")
            if d is None:
                values.append(None)
            elif d.get(f"{_SS_NS}Type") == "Number":
                values.append(float(d.text))
            else:
                values.append(d.text)
        if i == 0:
            columns = [str(v) for v in values]
            continue
        passes.append(dict(zip(columns, values)))
    params = [c for c in columns if c not in _METRIC_COLUMNS]
    for rec in passes:
        for k in ("Pass", "Trades", *params):
            v = rec.get(k)
            if isinstance(v, float) and v.is_integer():
                rec[k] = int(v)
    return OptimizationResult(title_el.text if title_el is not None else "", columns, passes, params)
