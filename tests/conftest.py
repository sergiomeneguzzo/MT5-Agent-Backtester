"""Shared fixtures: an MT5-style .xlsx builder and a fake MCP transport."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from mt5agent.client import MT5Client
from mt5agent.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"
NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def build_xlsx(rows: list[list[str | None]]) -> bytes:
    """Write rows like MT5 does: shared strings, parts encoded as UTF-16."""
    strings: list[str] = []
    index: dict[str, int] = {}
    xml_rows = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            if value is None:
                continue
            if value not in index:
                index[value] = len(strings)
                strings.append(value)
            cells.append(f'<c r="{_col(c)}{r}" t="s"><v>{index[value]}</v></c>')
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    shared = (f'<?xml version="1.0" encoding="UTF-16"?><sst xmlns="{NS}">'
              + "".join(f"<si><t>{esc(s)}</t></si>" for s in strings) + "</sst>")
    sheet = (f'<?xml version="1.0" encoding="UTF-16"?><worksheet xmlns="{NS}"><sheetData>'
             + "".join(xml_rows) + "</sheetData></worksheet>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", shared.encode("utf-16"))
        z.writestr("xl/worksheets/sheet1.xml", sheet.encode("utf-16"))
    return buf.getvalue()


def _pad(label: str, value: str) -> list[str | None]:
    return [label, None, None, value]


SAMPLE_ROWS: list[list[str | None]] = [
    ["Strategy Tester Report"],
    ["Some-Broker-Server (Build 6230)"],
    ["Settings"],
    _pad("Expert:", "Moving Average"),
    _pad("Symbol:", "EURUSD"),
    _pad("Period:", "H1 (2020.01.01 - 2021.12.31)"),
    _pad("Inputs:", "MovingPeriod=12"),
    [None, None, None, "MovingShift=6"],
    _pad("Company:", "Some Broker Ltd"),
    _pad("Initial Deposit:", "10000.000000"),
    ["Results"],
    ["Total Net Profit:", None, None, "150.000000", "Balance Drawdown Absolute:", None, None, "20.0"],
    ["Profit Factor:", None, None, "1.750000", "Expected Payoff:", None, None, "50.0"],
    ["Deals"],
    ["Time", "Deal", "Symbol", "Type", "Direction", "Volume", "Price", "Order",
     "Commission", "Swap", "Profit", "Balance", "Comment"],
    ["2020.01.01 00:00:00", "1", None, "balance", None, None, None, None,
     "0.00", "0.00", "10000.00", "10000.00", None],
    ["2020.03.02 10:00:00", "2", "EURUSD", "buy", "in", "0.10", "1.10000", "2", "-0.50", "0.00", "0.00", "9999.50", None],
    ["2020.03.03 10:00:00", "3", "EURUSD", "sell", "out", "0.10", "1.12000", "3", "-0.50", "-1.00", "200.00", "10198.00", None],
    ["2021.05.04 10:00:00", "4", "EURUSD", "sell", "in", "0.10", "1.20000", "4", "-0.50", "0.00", "0.00", "10197.50", None],
    ["2021.05.05 10:00:00", "5", "EURUSD", "buy", "out", "0.10", "1.20500", "5", "-0.50", "0.00", "-50.00", "10147.00", None],
    [None, None, None, None, None, None, None, None, "-2.00", "-1.00", "150.00", "10147.00", None],
]


@pytest.fixture
def sample_xlsx() -> bytes:
    return build_xlsx(SAMPLE_ROWS)


@pytest.fixture
def optimization_xml() -> bytes:
    return (FIXTURES / "optimization_ma_eurusd_h1.xml").read_bytes()


class FakeMT5:
    """In-memory stand-in for the MetaTrader 5 MCP server."""

    def __init__(self, files: dict[str, bytes] | None = None, charts=None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.files = dict(files or {})
        self.charts = list(charts or [])
        self.stats = json.loads((FIXTURES / "backtest_stats_ma_eurusd_h1.json").read_text())
        self.report_bytes: bytes = b""
        self.wait_rounds = 0
        self.charts_after_run: list[dict] = []

    def tool(self, name: str, args: dict):
        self.calls.append((name, args))
        if name == "get_workspace_info":
            return {"workspace": {"mql5_folder": r"C:\MT5\MQL5"},
                    "compiler": {"compiler_mql5_build": 6230},
                    "capabilities": {"can_run_backtest": True}}
        if name in ("tester_prepare_config", "tester_prepare_inputs"):
            return {"ok": True, "path": args["output_path"]}
        if name in ("tester_run_backtest", "tester_run_optimization"):
            self.charts.extend(self.charts_after_run)
            return {"ok": True, "run_id": "42", "status": "running" if self.wait_rounds else "stopped",
                    "timed_out": bool(self.wait_rounds)}
        if name == "tester_wait":
            self.wait_rounds -= 1
            return {"ok": True, "run_id": "42", "timed_out": self.wait_rounds > 0}
        if name == "tester_get_report":
            if "path" in args:
                self.files[args["path"]] = self.report_bytes
                return {"ok": True, "path": args["path"]}
            return self.stats
        if name == "read_binary_file":
            return {"ok": True, "encoding": "hex", "data": self.files[args["path"]].hex()}
        if name == "delete_file":
            self.files.pop(args["path"], None)
            return {"ok": True}
        if name == "list_open_charts":
            return {"charts": self.charts}
        if name == "chart_close":
            self.charts = [c for c in self.charts if str(c["chart_id"]) != args["chart_id"]]
            return {"ok": True}
        raise AssertionError(f"unexpected tool {name}")

    def transport(self, body: dict, headers: dict):
        assert headers["Authorization"] == "Bearer test-key"
        if "id" not in body:
            return "", {}
        method = body["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {}}
        elif method == "tools/list":
            result = {"tools": [{"name": n} for n in
                                ("tester_run_backtest", "trade_send_market_order", "list_open_charts")]}
        else:
            out = self.tool(body["params"]["name"], body["params"]["arguments"])
            result = {"content": [{"type": "text", "text": json.dumps(out)}], "isError": False}
        return json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}), {"Mcp-Session-Id": "s1"}


@pytest.fixture
def fake() -> FakeMT5:
    return FakeMT5()


@pytest.fixture
def client(fake: FakeMT5) -> MT5Client:
    return MT5Client(Settings("http://127.0.0.1:1/mcp", "test-key"), transport=fake.transport)
