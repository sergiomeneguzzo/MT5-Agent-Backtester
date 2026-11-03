from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..client import TRADING_PREFIXES, MT5Client
from ..config import DEFAULT_DEPOSIT, DEFAULT_LEVERAGE, DEFAULT_MODEL
from ..inputs import parse_assignments
from ..reports import BacktestReport, parse_report
from ..tester import MODELS, Tester
from .output import BOLD, DIM, Output


@dataclass
class Context:
    args: argparse.Namespace
    out: Output
    _client: MT5Client | None = None

    @property
    def client(self) -> MT5Client:
        if self._client is None:
            self._client = MT5Client.connect()
        return self._client

    @property
    def tester(self) -> Tester:
        return Tester(self.client)

    def run_options(self) -> dict:
        a = self.args
        return {"inputs": parse_assignments(a.param), "model": a.model, "deposit": a.deposit, "leverage": a.leverage}


@dataclass
class Command:
    name: str
    help: str
    handler: Callable[[Context], None]
    arguments: list[tuple[tuple, dict]] = field(default_factory=list)


COMMANDS: dict[str, Command] = {}


def arg(*flags: str, **options) -> tuple[tuple, dict]:
    return flags, options


def run_arguments(ranges: bool = False) -> list[tuple[tuple, dict]]:
    return [
        arg("expert", help="EA path relative to MQL5/Experts (no .ex5) or absolute"),
        arg("symbol"),
        arg("timeframe"),
        arg("start", help="YYYY-MM-DD"),
        arg("end", help="YYYY-MM-DD"),
        arg("-p", "--param", action="append", default=[],
            help="Name=start:stop:step or Name=value" if ranges else "Name=value"),
        arg("--model", default=DEFAULT_MODEL, choices=MODELS),
        arg("--deposit", type=float, default=DEFAULT_DEPOSIT),
        arg("--leverage", type=int, default=DEFAULT_LEVERAGE),
    ]


def command(name: str, help: str, *arguments: tuple[tuple, dict]):
    def register(handler: Callable[[Context], None]) -> Callable[[Context], None]:
        COMMANDS[name] = Command(name, help, handler, list(arguments))
        return handler
    return register


@command("doctor", "check the connection to MetaTrader 5")
def doctor(ctx: Context) -> None:
    workspace = ctx.client.workspace
    info = {
        "connected": True,
        "url": ctx.client.settings.url,
        "build": workspace.get("compiler", {}).get("compiler_mql5_build"),
        "can_run_backtest": workspace.get("capabilities", {}).get("can_run_backtest"),
        "can_run_optimization": workspace.get("capabilities", {}).get("can_run_optimization"),
        "trading_tools": "ALLOWED" if ctx.client.allow_trading else "blocked",
    }
    ctx.out.emit(info, lambda: ctx.out.pairs(info, ("check", "value")))


@command("tools", "list the MCP tools exposed by the terminal (trade_* hidden)")
def tools(ctx: Context) -> None:
    items = ctx.client.tools()

    def render() -> None:
        for t in items:
            print(f"{t['name']:<40} {ctx.out.paint(t.get('description', '')[:70], DIM)}")
        ctx.out.line(f"\n{len(items)} tools ({'/'.join(TRADING_PREFIXES)}* hidden)", DIM)

    ctx.out.emit([t["name"] for t in items], render)


@command("experts", "list compiled Expert Advisors", arg("--filter", default=""))
def experts(ctx: Context) -> None:
    programs = ctx.tester.experts(ctx.args.filter)
    ctx.out.emit(programs, lambda: ctx.out.table(("expert", "build time"),
                                                 [(p["name"], p.get("build_time", "")) for p in programs]))


@command("inputs", "show the inputs of an Expert Advisor", arg("expert"))
def inputs(ctx: Context) -> None:
    info = ctx.tester.expert_inputs(ctx.args.expert)
    rows = [(p["name"], p["type"], p.get("value")) for p in info.get("parameters", [])]
    ctx.out.emit(info, lambda: ctx.out.table(("input", "type", "default"), rows, align_left=2))


@command("backtest", "run one backtest", *run_arguments(),
         arg("--plot", help="save an equity + drawdown chart (PNG)"),
         arg("--save", help="save the raw .xlsx report"))
def backtest(ctx: Context) -> None:
    a = ctx.args
    run = ctx.tester.backtest(a.expert, a.symbol, a.timeframe, a.start, a.end, **ctx.run_options())
    yearly = run.report.yearly_returns() if run.report else {}
    ctx.out.emit({"run_id": run.run_id, **run.summary(), "yearly_return_pct": _rounded(yearly)},
                 lambda: _print_backtest(ctx.out, run.summary(), yearly))
    if a.plot and run.report:
        from ..plots import plot_equity
        plot_equity(run.report, a.plot)
    if a.save and run.raw:
        Path(a.save).write_bytes(run.raw)


@command("optimize", "grid or genetic optimization", *run_arguments(ranges=True),
         arg("--criterion", default="profit_factor"),
         arg("--top", type=int, default=10),
         arg("--plot", help="save a heatmap of the first two optimized inputs (PNG)"))
def optimize(ctx: Context) -> None:
    a = ctx.args
    run = ctx.tester.optimize(a.expert, a.symbol, a.timeframe, a.start, a.end,
                              criterion=a.criterion, **ctx.run_options())
    result, top = run.result, run.result.top(a.top)

    def render() -> None:
        columns = [*result.params, "Profit", "Profit Factor", "Equity DD %", "Trades"]
        ctx.out.line(f"{run.passes} passes in {run.seconds:.0f} s, top {len(top)}", BOLD)
        ctx.out.table(columns, [[p.get(c) for c in columns] for p in top], align_left=0)
        ctx.out.line(f"\n{result.profitable}/{run.passes} passes profitable. The best pass is in-sample, "
                     "check it with `mt5agent walkforward`.", DIM)

    ctx.out.emit({"run_id": run.run_id, "passes": run.passes, "profitable_passes": result.profitable,
                  "params": result.params, "top": top}, render)
    if a.plot and len(result.params) >= 2:
        from ..plots import plot_heatmap
        plot_heatmap(result, result.params[0], result.params[1], a.plot)


@command("walkforward", "rolling or anchored walk-forward analysis", *run_arguments(ranges=True),
         arg("--is-months", type=int, default=24),
         arg("--oos-months", type=int, default=6),
         arg("--anchored", action="store_true"),
         arg("--min-trades", type=int, default=30),
         arg("--plot", help="save the stitched out-of-sample equity (PNG)"))
def walkforward(ctx: Context) -> None:
    a = ctx.args

    def progress(fold) -> None:
        if not ctx.out.as_json:
            oos = fold.oos_summary
            print(f"{fold.fold.label()}  {fold.best_params}  "
                  f"OOS PF {oos.get('profit_factor')}  net {oos.get('net_profit')}")

    wf = ctx.tester.walk_forward(a.expert, a.symbol, a.timeframe, a.start, a.end,
                                 is_months=a.is_months, oos_months=a.oos_months, anchored=a.anchored,
                                 min_trades=a.min_trades, on_fold=progress, **ctx.run_options())
    folds = [{"fold": f.fold.label(), "params": f.best_params, "oos": f.oos_summary} for f in wf.folds]
    ctx.out.emit({"summary": wf.summary(), "folds": folds},
                 lambda: (print(), ctx.out.pairs(wf.summary(), ("out-of-sample", "value"))))
    if a.plot:
        from ..plots import plot_walk_forward
        plot_walk_forward(wf, a.plot)


@command("report", "summarize a saved .xlsx or .xml report (no terminal needed)", arg("path"))
def report(ctx: Context) -> None:
    parsed = parse_report(Path(ctx.args.path).read_bytes())
    if isinstance(parsed, BacktestReport):
        data = {"expert": parsed.expert, "symbol": parsed.symbol, "period": parsed.period,
                "inputs": parsed.inputs, **parsed.summary(),
                "yearly_return_pct": _rounded(parsed.yearly_returns())}
    else:
        best = parsed.best()
        data = {"title": parsed.title, "passes": len(parsed.passes), "params": parsed.params,
                "profitable_passes": parsed.profitable,
                "best": {k: best.get(k) for k in (*parsed.params, "Profit Factor", "Profit", "Trades")}}
    ctx.out.emit(data, lambda: ctx.out.pairs(data))


def _print_backtest(out: Output, summary: dict, yearly: dict) -> None:
    pf = summary.get("profit_factor") or 0
    out.line("Strategy Tester result", BOLD)
    out.table(("metric", "value"), [
        ("Net profit", f"{summary.get('profit', 0):,.2f}"),
        ("Profit factor", out.signed(pf - 1, f"{pf:.2f}")),
        ("Trades", summary.get("trades")),
        ("Max equity DD", f"{summary.get('drawdown_percent_equity', 0):.2f}%"),
        ("Recovery factor", summary.get("recovery_factor")),
        ("Sharpe", summary.get("sharpe_ratio")),
        ("Run time", f"{summary.get('seconds')} s"),
    ])
    if yearly:
        print()
        out.table(("year", "return"), [(year, out.signed(r, f"{r:+.2f}%")) for year, r in yearly.items()])


def _rounded(yearly: dict) -> dict:
    return {str(year): round(value, 2) for year, value in yearly.items()}
