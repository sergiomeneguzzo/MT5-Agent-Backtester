from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..config import DEFAULT_DEPOSIT, DEFAULT_LEVERAGE, DEFAULT_MODEL
from ..inputs import parse_inputs
from ..tester import CRITERIA, MODELS, Tester

Handler = Callable[[Tester, dict], Any]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict
    handler: Handler

    def spec(self) -> dict:
        return {"name": self.name, "description": self.description, "inputSchema": self.schema}


TOOLS: dict[str, Tool] = {}

RUN_PROPERTIES = {
    "expert": {"type": "string",
               "description": "EA path relative to MQL5\\Experts without extension, or an absolute .ex5 path"},
    "symbol": {"type": "string"},
    "timeframe": {"type": "string", "description": "M1, M5, M15, M30, H1, H4, D1"},
    "start": {"type": "string", "description": "YYYY-MM-DD"},
    "end": {"type": "string", "description": "YYYY-MM-DD"},
    "model": {"type": "string", "enum": list(MODELS), "default": DEFAULT_MODEL},
    "deposit": {"type": "number", "default": DEFAULT_DEPOSIT},
    "leverage": {"type": "integer", "default": DEFAULT_LEVERAGE},
}
RUN_REQUIRED = ["expert", "symbol", "timeframe", "start", "end"]
RANGES = {"type": "object", "additionalProperties": True,
          "description": "{name: [start, stop, step]} to optimize, plain values stay fixed"}


def schema(required: list[str] | None = None, **properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


def run_schema(*extra_required: str, **properties: dict) -> dict:
    return schema(RUN_REQUIRED + list(extra_required), **RUN_PROPERTIES, **properties)


def tool(name: str, description: str, input_schema: dict):
    def register(handler: Handler) -> Handler:
        TOOLS[name] = Tool(name, description, input_schema, handler)
        return handler
    return register


def run_args(args: dict) -> tuple[tuple, dict]:
    positional = tuple(args[k] for k in RUN_REQUIRED)
    options = {k: args.get(k, RUN_PROPERTIES[k]["default"]) for k in ("model", "deposit", "leverage")}
    return positional, options


@tool("list_experts", "List compiled Expert Advisors available to the Strategy Tester.",
      schema(filter={"type": "string"}))
def list_experts(tester: Tester, args: dict) -> list[dict]:
    return [{"name": p.get("name"), "path": p.get("path"), "build_time": p.get("build_time")}
            for p in tester.experts(args.get("filter", ""))]


@tool("expert_inputs", "Input parameters (name, type, default), version and build time of an Expert Advisor.",
      schema(["expert"], expert=RUN_PROPERTIES["expert"]))
def expert_inputs(tester: Tester, args: dict) -> dict:
    info = tester.expert_inputs(args["expert"])
    return {"name": info.get("name"), "version": info.get("version"),
            "build_time": info.get("build_time"), "inputs": info.get("parameters", [])}


@tool("run_backtest", "Run one backtest in the MT5 Strategy Tester. Returns net profit, profit factor, "
      "drawdown, trades and yearly returns.",
      run_schema(inputs={"type": "object", "additionalProperties": True}))
def run_backtest(tester: Tester, args: dict) -> dict:
    positional, options = run_args(args)
    run = tester.backtest(*positional, inputs=args.get("inputs"), **options)
    yearly = run.report.yearly_returns() if run.report else {}
    return {"run_id": run.run_id, **run.summary(),
            "yearly_return_pct": {str(y): round(r, 2) for y, r in yearly.items()}}


@tool("run_optimization", "Optimize EA inputs in the MT5 Strategy Tester. Returns the grid size, how many "
      "passes were profitable and the top passes. The best pass is in-sample: confirm it with run_walk_forward.",
      run_schema("inputs", inputs=RANGES,
                 criterion={"type": "string", "enum": list(CRITERIA), "default": "profit_factor"},
                 top={"type": "integer", "default": 10}))
def run_optimization(tester: Tester, args: dict) -> dict:
    positional, options = run_args(args)
    run = tester.optimize(*positional, inputs=parse_inputs(args["inputs"]),
                          criterion=args.get("criterion", "profit_factor"), **options)
    return {"run_id": run.run_id, "passes": run.passes, "seconds": round(run.seconds, 1),
            "profitable_passes": run.result.profitable, "params": run.result.params,
            "top": run.result.top(args.get("top", 10))}


@tool("run_walk_forward", "Walk-forward analysis: optimize on each in-sample window, trade the winner on the "
      "next out-of-sample window and stitch the out-of-sample trades together.",
      run_schema("inputs", inputs=RANGES,
                 is_months={"type": "integer", "default": 24},
                 oos_months={"type": "integer", "default": 6},
                 anchored={"type": "boolean", "default": False},
                 min_trades={"type": "integer", "default": 30}))
def run_walk_forward(tester: Tester, args: dict) -> dict:
    positional, options = run_args(args)
    wf = tester.walk_forward(*positional, inputs=parse_inputs(args["inputs"]),
                             is_months=args.get("is_months", 24), oos_months=args.get("oos_months", 6),
                             anchored=args.get("anchored", False), min_trades=args.get("min_trades", 30),
                             **options)
    return {"summary": wf.summary(),
            "folds": [{"fold": f.fold.label(), "params": f.best_params,
                       "is_profit_factor": f.is_metrics.get("Profit Factor"), "oos": f.oos_summary}
                      for f in wf.folds]}
