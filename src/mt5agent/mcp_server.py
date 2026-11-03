"""A backtest-only MCP server for AI agents (stdio transport).

Point Claude Code, Cursor, Codex or any MCP client at this server instead of
the raw MetaTrader 5 one. Agents get a handful of high-level, research-oriented
tools — and no way to reach ``trade_*``:

    claude mcp add mt5-backtester -- mt5agent-mcp

Every tool returns compact JSON designed to fit in an agent's context window
(summaries and the top passes, not 3,000 raw deals).
"""
from __future__ import annotations

import json
import sys
import traceback
from collections.abc import Callable
from typing import Any

from . import __version__
from .client import MT5Client
from .inputs import Range
from .tester import MODELS, Tester

PROTOCOL_VERSION = "2025-06-18"

_COMMON = {
    "expert": {"type": "string", "description": "EA path relative to MQL5\\Experts without extension "
               "(e.g. 'Examples\\\\Moving Average\\\\Moving Average') or an absolute .ex5 path."},
    "symbol": {"type": "string"},
    "timeframe": {"type": "string", "description": "M1, M5, M15, M30, H1, H4, D1 ..."},
    "start": {"type": "string", "description": "YYYY-MM-DD"},
    "end": {"type": "string", "description": "YYYY-MM-DD"},
    "model": {"type": "string", "enum": list(MODELS), "default": "open prices"},
    "deposit": {"type": "number", "default": 10000},
    "leverage": {"type": "integer", "default": 100},
}
_RANGES = {"type": "object", "description": "Inputs to optimize: {name: [start, stop, step]}. "
           "Plain values are kept fixed.", "additionalProperties": True}


def _parse_inputs(raw: dict | None) -> dict:
    out: dict[str, Any] = {}
    for k, v in (raw or {}).items():
        if isinstance(v, list) and len(v) == 3:
            out[k] = Range(*v)
        elif isinstance(v, dict) and {"start", "stop", "step"} <= v.keys():
            out[k] = Range(v["start"], v["stop"], v["step"])
        else:
            out[k] = v
    return out


class Server:
    def __init__(self, tester_factory: Callable[[], Tester] | None = None) -> None:
        self._factory = tester_factory or (lambda: Tester(MT5Client.connect()))
        self._tester: Tester | None = None
        self.tools: dict[str, tuple[dict, Callable[[dict], Any]]] = {
            "list_experts": ({
                "description": "List compiled Expert Advisors available to the Strategy Tester.",
                "inputSchema": {"type": "object", "properties": {"filter": {"type": "string"}}},
            }, self._list_experts),
            "expert_inputs": ({
                "description": "Show the input parameters (name, type, default) of an Expert Advisor.",
                "inputSchema": {"type": "object", "properties": {"expert": _COMMON["expert"]},
                                "required": ["expert"]},
            }, self._expert_inputs),
            "run_backtest": ({
                "description": "Run one MT5 Strategy Tester backtest and return the key metrics "
                               "(net profit, profit factor, drawdown, trades, yearly returns).",
                "inputSchema": {"type": "object", "properties": {
                    **_COMMON, "inputs": {"type": "object", "additionalProperties": True}},
                    "required": ["expert", "symbol", "timeframe", "start", "end"]},
            }, self._backtest),
            "run_optimization": ({
                "description": "Optimize EA inputs over a grid in the MT5 Strategy Tester. Returns "
                               "grid size and the top passes. Warning: the best pass is in-sample "
                               "— use run_walk_forward before trusting it.",
                "inputSchema": {"type": "object", "properties": {
                    **_COMMON, "inputs": _RANGES,
                    "criterion": {"type": "string", "default": "profit_factor",
                                  "enum": ["profit_factor", "balance", "recovery_factor", "sharpe",
                                           "drawdown", "expected_payoff", "custom"]},
                    "top": {"type": "integer", "default": 10}},
                    "required": ["expert", "symbol", "timeframe", "start", "end", "inputs"]},
            }, self._optimize),
            "run_walk_forward": ({
                "description": "Rolling walk-forward: optimize on each in-sample window, trade the "
                               "winner on the next out-of-sample window, stitch the OOS trades. "
                               "Returns per-fold params and the honest OOS summary.",
                "inputSchema": {"type": "object", "properties": {
                    **_COMMON, "inputs": _RANGES,
                    "is_months": {"type": "integer", "default": 24},
                    "oos_months": {"type": "integer", "default": 6},
                    "anchored": {"type": "boolean", "default": False},
                    "min_trades": {"type": "integer", "default": 30}},
                    "required": ["expert", "symbol", "timeframe", "start", "end", "inputs"]},
            }, self._walk_forward),
        }

    @property
    def tester(self) -> Tester:
        if self._tester is None:
            self._tester = self._factory()
        return self._tester

    # -- tool implementations ----------------------------------------------
    @staticmethod
    def _common(a: dict) -> dict:
        return {"model": a.get("model", "open prices"), "deposit": a.get("deposit", 10000),
                "leverage": a.get("leverage", 100)}

    def _list_experts(self, a: dict) -> Any:
        return [{"name": p.get("name"), "path": p.get("path"), "build_time": p.get("build_time")}
                for p in self.tester.experts(a.get("filter", ""))]

    def _expert_inputs(self, a: dict) -> Any:
        info = self.tester.expert_inputs(a["expert"])
        return {"name": info.get("name"), "version": info.get("version"),
                "build_time": info.get("build_time"), "inputs": info.get("parameters", [])}

    def _backtest(self, a: dict) -> Any:
        run = self.tester.backtest(a["expert"], a["symbol"], a["timeframe"], a["start"], a["end"],
                                   inputs=a.get("inputs"), **self._common(a))
        out = {"run_id": run.run_id, **run.summary()}
        if run.report:
            from .metrics import yearly_returns
            out["yearly_return_pct"] = {str(y): round(r, 2) for y, r in
                                        yearly_returns(run.report.trades, run.report.initial_deposit).items()}
        return out

    def _optimize(self, a: dict) -> Any:
        run = self.tester.optimize(a["expert"], a["symbol"], a["timeframe"], a["start"], a["end"],
                                   inputs=_parse_inputs(a["inputs"]),
                                   criterion=a.get("criterion", "profit_factor"), **self._common(a))
        top = sorted(run.result.passes, key=lambda p: p.get("Result") or 0, reverse=True)[: a.get("top", 10)]
        profitable = sum(1 for p in run.result.passes if (p.get("Profit") or 0) > 0)
        return {"run_id": run.run_id, "passes": run.passes, "seconds": round(run.seconds, 1),
                "profitable_passes": profitable, "params": run.result.params, "top": top}

    def _walk_forward(self, a: dict) -> Any:
        wf = self.tester.walk_forward(a["expert"], a["symbol"], a["timeframe"], a["start"], a["end"],
                                      inputs=_parse_inputs(a["inputs"]),
                                      is_months=a.get("is_months", 24), oos_months=a.get("oos_months", 6),
                                      anchored=a.get("anchored", False),
                                      min_trades=a.get("min_trades", 30), **self._common(a))
        return {"summary": wf.summary(), "folds": [{
            "fold": f.fold.label(), "params": f.best_params,
            "is_profit_factor": f.is_metrics.get("Profit Factor"),
            "oos": f.oos_summary} for f in wf.folds]}

    # -- JSON-RPC -----------------------------------------------------------
    def handle(self, msg: dict) -> dict | None:
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:                      # notification
            return None
        try:
            if method == "initialize":
                result = {"protocolVersion": PROTOCOL_VERSION,
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "mt5-agent-backtester", "version": __version__},
                          "instructions": "Backtest-only access to the MetaTrader 5 Strategy Tester. "
                                          "No trading tools are exposed."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": [{"name": n, **spec} for n, (spec, _) in self.tools.items()]}
            elif method == "tools/call":
                name = msg["params"]["name"]
                if name not in self.tools:
                    raise KeyError(f"Unknown tool {name!r}")
                try:
                    data = self.tools[name][1](msg["params"].get("arguments") or {})
                    result = {"content": [{"type": "text", "text": json.dumps(data, default=str)}],
                              "isError": False}
                except Exception as exc:     # tool errors go back to the agent, not the transport
                    result = {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                              "isError": True}
            else:
                return {"jsonrpc": "2.0", "id": mid,
                        "error": {"code": -32601, "message": f"Method not found: {method}"}}
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(exc)}}


def main() -> None:
    server = Server()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            reply = server.handle(json.loads(line))
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        except Exception:                    # never die on a bad message
            traceback.print_exc(file=sys.stderr)
            continue
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
