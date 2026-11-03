"""Command line interface.  Every command accepts ``--json`` for agents and scripts.

    mt5agent doctor
    mt5agent experts --filter Moving
    mt5agent backtest "Examples/Moving Average/Moving Average" EURUSD H1 2020-01-01 2025-12-31
    mt5agent optimize "Examples/Moving Average/Moving Average" EURUSD H1 2020-01-01 2025-12-31 \
        -p MovingPeriod=10:100:10 -p MovingShift=0:10:2
    mt5agent walkforward ... -p MovingPeriod=10:100:10 --is-months 24 --oos-months 12
    mt5agent report path/to/report.xlsx          # offline, no terminal needed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .client import TRADING_PREFIXES, MT5Client
from .inputs import Range
from .metrics import yearly_returns
from .report import parse_backtest_xlsx, parse_optimization_xml
from .tester import MODELS, Tester

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def _color(enabled: bool):
    def c(text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if enabled else text
    return c


def _parse_value(text: str) -> Any:
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def parse_params(items: list[str]) -> dict:
    """``Name=12`` (fixed) or ``Name=start:stop:step`` (optimize)."""
    out: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"bad parameter {item!r}: expected Name=value or Name=start:stop:step")
        name, value = item.split("=", 1)
        parts = value.split(":")
        out[name] = Range(*(float(p) for p in parts)) if len(parts) == 3 else _parse_value(value)
    return out


def _table(rows: list[list[Any]], header: list[str]) -> str:
    cells = [[str(h) for h in header]] + [[("" if v is None else str(v)) for v in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(header))]
    line = lambda r: "  ".join(v.rjust(w) if i else v.ljust(w) for i, (v, w) in enumerate(zip(r, widths)))
    return "\n".join([line(cells[0]), "  ".join("─" * w for w in widths), *map(line, cells[1:])])


def _print_backtest(summary: dict, yearly: dict, c) -> None:
    pf = summary.get("profit_factor") or 0
    tone = GREEN if pf >= 1 else RED
    print(c("Strategy Tester result", BOLD))
    rows = [
        ["Net profit", f"{summary.get('profit', 0):,.2f}"],
        ["Profit factor", c(f"{pf:.2f}", tone)],
        ["Trades", summary.get("trades")],
        ["Max equity DD", f"{summary.get('drawdown_percent_equity', 0):.2f}%"],
        ["Recovery factor", summary.get("recovery_factor")],
        ["Sharpe", summary.get("sharpe_ratio")],
        ["Run time", f"{summary.get('seconds')} s"],
    ]
    print(_table(rows, ["metric", "value"]))
    if yearly:
        print()
        print(_table([[y, c(f"{r:+.2f}%", GREEN if r >= 0 else RED)] for y, r in yearly.items()],
                     ["year", "return"]))


def _common(p: argparse.ArgumentParser, ranges: bool = False) -> None:
    p.add_argument("expert", help="EA path relative to MQL5/Experts (no .ex5) or absolute")
    p.add_argument("symbol")
    p.add_argument("timeframe")
    p.add_argument("start", help="YYYY-MM-DD")
    p.add_argument("end", help="YYYY-MM-DD")
    p.add_argument("-p", "--param", action="append", default=[],
                   help="Name=value" + (" or Name=start:stop:step" if ranges else ""))
    p.add_argument("--model", default="open prices", choices=MODELS)
    p.add_argument("--deposit", type=float, default=10_000)
    p.add_argument("--leverage", type=int, default=100)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="mt5agent", description="Drive the MetaTrader 5 Strategy Tester from code.")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--no-color", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check the connection to MetaTrader 5")
    sub.add_parser("tools", help="list the MCP tools the terminal exposes (trade_* hidden)")
    e = sub.add_parser("experts", help="list compiled Expert Advisors")
    e.add_argument("--filter", default="")
    i = sub.add_parser("inputs", help="show the inputs of an Expert Advisor")
    i.add_argument("expert")

    b = sub.add_parser("backtest", help="run one backtest")
    _common(b)
    b.add_argument("--plot", help="save equity + drawdown chart (PNG, needs the plot extra)")
    b.add_argument("--save", help="save the raw .xlsx report locally")

    o = sub.add_parser("optimize", help="grid / genetic optimization")
    _common(o, ranges=True)
    o.add_argument("--criterion", default="profit_factor")
    o.add_argument("--top", type=int, default=10)
    o.add_argument("--plot", help="save a 2-parameter heatmap (PNG)")

    w = sub.add_parser("walkforward", help="rolling walk-forward analysis")
    _common(w, ranges=True)
    w.add_argument("--is-months", type=int, default=24)
    w.add_argument("--oos-months", type=int, default=6)
    w.add_argument("--anchored", action="store_true")
    w.add_argument("--min-trades", type=int, default=30)
    w.add_argument("--plot", help="save the stitched out-of-sample equity (PNG)")

    r = sub.add_parser("report", help="parse a saved .xlsx / .xml report (offline)")
    r.add_argument("path")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    c = _color(sys.stdout.isatty() and not args.no_color and not args.json)
    emit = lambda obj: print(json.dumps(obj, indent=2, default=str))

    if args.cmd == "report":
        data = Path(args.path).read_bytes()
        if data[:2] == b"PK":
            rep = parse_backtest_xlsx(data)
            out = {"expert": rep.expert, "symbol": rep.symbol, "period": rep.period,
                   "inputs": rep.inputs, **rep.summary(),
                   "yearly_return_pct": {str(k): round(v, 2) for k, v in
                                         yearly_returns(rep.trades, rep.initial_deposit).items()}}
        else:
            opt = parse_optimization_xml(data)
            out = {"title": opt.title, "passes": len(opt.passes), "params": opt.params,
                   "best": opt.best()}
        emit(out) if args.json else print(_table([[k, v] for k, v in out.items()], ["field", "value"]))
        return 0

    client = MT5Client.connect()
    tester = Tester(client)

    if args.cmd == "doctor":
        ws = client.workspace
        info = {"connected": True, "url": client.settings.url,
                "build": ws.get("compiler", {}).get("compiler_mql5_build"),
                "can_run_backtest": ws.get("capabilities", {}).get("can_run_backtest"),
                "can_run_optimization": ws.get("capabilities", {}).get("can_run_optimization"),
                "trading_tools": "blocked" if not client.allow_trading else "ALLOWED"}
        emit(info) if args.json else print(_table([[k, v] for k, v in info.items()], ["check", "value"]))
    elif args.cmd == "tools":
        tools = client.tools()
        if args.json:
            emit([t["name"] for t in tools])
        else:
            for t in tools:
                print(f"{t['name']:<40} {c(t.get('description', '')[:70], DIM)}")
            print(c(f"\n{len(tools)} tools ({'/'.join(TRADING_PREFIXES)}* hidden)", DIM))
    elif args.cmd == "experts":
        progs = tester.experts(args.filter)
        emit(progs) if args.json else print(_table([[p["name"], p.get("build_time", "")] for p in progs],
                                                   ["expert", "build time"]))
    elif args.cmd == "inputs":
        info = tester.expert_inputs(args.expert)
        params = info.get("parameters", [])
        emit(info) if args.json else print(_table([[p["name"], p["type"], p.get("value")] for p in params],
                                                  ["input", "type", "default"]))
    elif args.cmd == "backtest":
        run = tester.backtest(args.expert, args.symbol, args.timeframe, args.start, args.end,
                              inputs=parse_params(args.param), model=args.model,
                              deposit=args.deposit, leverage=args.leverage)
        yearly = {str(k): round(v, 2) for k, v in
                  yearly_returns(run.report.trades, run.report.initial_deposit).items()} if run.report else {}
        if args.json:
            emit({"run_id": run.run_id, **run.summary(), "yearly_return_pct": yearly})
        else:
            _print_backtest(run.summary(), yearly, c)
        if args.plot and run.report:
            from .plots import plot_equity
            plot_equity(run.report, args.plot)
        if args.save and run.raw:
            Path(args.save).write_bytes(run.raw)
    elif args.cmd == "optimize":
        run = tester.optimize(args.expert, args.symbol, args.timeframe, args.start, args.end,
                              inputs=parse_params(args.param), criterion=args.criterion,
                              model=args.model, deposit=args.deposit, leverage=args.leverage)
        res = run.result
        top = sorted(res.passes, key=lambda p: p.get("Result") or 0, reverse=True)[: args.top]
        if args.json:
            emit({"run_id": run.run_id, "passes": run.passes, "params": res.params, "top": top})
        else:
            cols = [*res.params, "Profit", "Profit Factor", "Equity DD %", "Trades"]
            print(c(f"{run.passes} passes in {run.seconds:.0f} s — top {len(top)}", BOLD))
            print(_table([[p.get(k) for k in cols] for p in top], cols))
            profitable = sum(1 for p in res.passes if (p.get("Profit") or 0) > 0)
            print(c(f"\n{profitable}/{run.passes} passes profitable. The best pass is in-sample: "
                    "validate it with `mt5agent walkforward`.", DIM))
        if args.plot and len(res.params) >= 2:
            from .plots import plot_heatmap
            plot_heatmap(res, res.params[0], res.params[1], args.plot)
    elif args.cmd == "walkforward":
        def progress(fr):
            if not args.json:
                s = fr.oos_summary
                print(f"{fr.fold.label()}  {fr.best_params}  OOS PF {s.get('profit_factor')}  "
                      f"net {s.get('net_profit')}")
        wf = tester.walk_forward(args.expert, args.symbol, args.timeframe, args.start, args.end,
                                 inputs=parse_params(args.param), is_months=args.is_months,
                                 oos_months=args.oos_months, anchored=args.anchored,
                                 min_trades=args.min_trades, model=args.model,
                                 deposit=args.deposit, leverage=args.leverage, on_fold=progress)
        summary = wf.summary()
        if args.json:
            emit({"summary": summary, "folds": [{"fold": f.fold.label(), "params": f.best_params,
                                                  "oos": f.oos_summary} for f in wf.folds]})
        else:
            print()
            print(_table([[k, v] for k, v in summary.items()], ["out-of-sample", "value"]))
        if args.plot:
            from .plots import plot_walk_forward
            plot_walk_forward(wf, args.plot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
