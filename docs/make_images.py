"""Regenerate the README images from real Strategy Tester outputs.

    python docs/make_images.py --xlsx report.xlsx --stats stats.json --opt optimization.xml \
        [--wf walkforward.json]

The inputs come from a real run of MetaQuotes' bundled "Moving Average" example EA
(EURUSD H1, 2020-2025, open prices, 10,000 USD). Requires: pip install -e ".[dev]" rich
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rich.console import Console
from rich.json import JSON
from rich.table import Table
from rich.text import Text

from mt5agent.plots import plot_equity, plot_heatmap, plot_walk_forward
from mt5agent.reports import Trade, parse_backtest_xlsx, parse_optimization_xml
from mt5agent.walkforward import Fold, FoldResult, WalkForwardResult

OUT = Path(__file__).parent / "images"
EA = "Examples/Moving Average/Moving Average"


def _console(width: int = 100) -> Console:
    return Console(record=True, width=width, force_terminal=True, color_system="truecolor", highlight=False)


def _prompt(con: Console, cmd: str) -> None:
    con.print(Text("$ ", style="bold #3fb950") + Text(cmd, style="bold #c9d1d9"))


def term_backtest(stats: dict, yearly: dict) -> None:
    con = _console(92)
    _prompt(con, f'mt5agent backtest "{EA}" EURUSD H1 2020-01-01 2025-12-31 --plot equity.png')
    con.print("[#8b949e]→ tester_prepare_config · tester_run_backtest · tester_get_report · "
              "read_binary_file[/]")
    con.print("[#8b949e]→ temp .ini/.set/.xlsx deleted · 0 charts left open[/]\n")
    t = Table(title="Strategy Tester result", title_justify="left", title_style="bold #c9d1d9",
              border_style="#30363d", header_style="bold #58a6ff")
    t.add_column("metric")
    t.add_column("value", justify="right")
    pf = stats["profit_factor"]
    t.add_row("Net profit", f"{stats['profit']:,.2f}")
    t.add_row("Profit factor", Text(f"{pf:.2f}", style="bold #3fb950" if pf >= 1 else "bold #f85149"))
    t.add_row("Trades", str(stats["trades"]))
    t.add_row("Max equity DD", f"{stats['drawdown_percent_equity']:.2f}%")
    t.add_row("Recovery factor", f"{stats['recovery_factor']:.2f}")
    t.add_row("Sharpe", f"{stats['sharpe_ratio']:.2f}")
    t.add_row("Run time", "20.3 s")
    y = Table(title="Yearly return", title_justify="left", title_style="bold #c9d1d9",
              border_style="#30363d", header_style="bold #58a6ff")
    y.add_column("year")
    y.add_column("return", justify="right")
    for k, v in yearly.items():
        y.add_row(str(k), Text(f"{v:+.2f}%", style="#3fb950" if v >= 0 else "#f85149"))
    grid = Table.grid(padding=(0, 6))
    grid.add_row(t, y)
    con.print(grid)
    con.save_svg(str(OUT / "terminal-backtest.svg"), title="mt5agent backtest")


def term_optimize(opt) -> None:
    con = _console(104)
    _prompt(con, f'mt5agent optimize "{EA}" EURUSD H1 2020-01-01 2025-12-31 '
                 "-p MovingPeriod=10:100:10 -p MovingShift=0:10:2")
    con.print("[#8b949e]→ 60 combinations · complete grid · criterion profit_factor_max · 14 s[/]\n")
    t = Table(border_style="#30363d", header_style="bold #58a6ff",
              title="Top 8 of 60 passes", title_justify="left", title_style="bold #c9d1d9")
    for col in ("MovingPeriod", "MovingShift", "Profit", "Profit Factor", "Equity DD %", "Trades"):
        t.add_column(col, justify="right")
    top = sorted(opt.passes, key=lambda p: p["Profit Factor"], reverse=True)[:8]
    for p in top:
        pf = p["Profit Factor"]
        t.add_row(str(p["MovingPeriod"]), str(p["MovingShift"]), f"{p['Profit']:,.2f}",
                  Text(f"{pf:.3f}", style="#3fb950" if pf >= 1 else "#f85149"),
                  f"{p['Equity DD %']:.1f}", str(p["Trades"]))
    con.print(t)
    profitable = sum(1 for p in opt.passes if p["Profit"] > 0)
    con.print(f"\n[#d29922]⚠ {profitable}/60 passes profitable. The best pass is in-sample: "
              "validate it with `mt5agent walkforward`.[/]")
    con.save_svg(str(OUT / "terminal-optimize.svg"), title="mt5agent optimize")


def agent_session(stats: dict, yearly: dict, opt) -> None:
    con = _console(100)
    con.print("[bold #d2a8ff]You[/]  Is the MetaQuotes Moving Average EA worth anything on EURUSD H1? "
              "Test 2020-2025,\n     then see if tuning MovingPeriod/MovingShift helps.\n")
    con.print("[bold #f0883e]Agent[/] [#8b949e]⏺ mt5-backtester · run_backtest[/]")
    call = {"expert": EA, "symbol": "EURUSD", "timeframe": "H1", "start": "2020-01-01", "end": "2025-12-31"}
    con.print(JSON(json.dumps(call), indent=None), soft_wrap=False)
    res = {"profit": stats["profit"], "profit_factor": stats["profit_factor"], "trades": stats["trades"],
           "drawdown_percent_equity": stats["drawdown_percent_equity"],
           "yearly_return_pct": {str(k): round(v, 2) for k, v in yearly.items()}}
    con.print("[#8b949e]  ⎿[/] ", end="")
    con.print(JSON(json.dumps(res), indent=None), soft_wrap=False)
    con.print("\n[bold #f0883e]Agent[/] [#8b949e]⏺ mt5-backtester · run_optimization[/]")
    con.print(JSON(json.dumps({**call, "inputs": {"MovingPeriod": [10, 100, 10], "MovingShift": [0, 10, 2]}}),
                   indent=None), soft_wrap=False)
    best = opt.best()
    profitable = sum(1 for p in opt.passes if p["Profit"] > 0)
    con.print("[#8b949e]  ⎿[/] ", end="")
    con.print(JSON(json.dumps({"passes": 60, "profitable_passes": profitable,
                               "top": [{k: best[k] for k in ("MovingPeriod", "MovingShift", "Profit Factor",
                                                             "Trades")}]}), indent=None), soft_wrap=False)
    con.print(
        "\n[bold #f0883e]Agent[/] With default inputs the EA loses [bold #f85149]21.7%[/] "
        f"(PF {stats['profit_factor']:.2f}, {stats['drawdown_percent_equity']:.0f}% DD).\n"
        f"      Only {profitable} of 60 combinations make money and the best one (PF {best['Profit Factor']:.2f})"
        " is\n      in-sample. Next step: a walk-forward to check whether any of it survives\n"
        "      out-of-sample. [#8b949e]No orders were sent — trade_* tools are not exposed.[/]")
    con.save_svg(str(OUT / "agent-session.svg"), title="Claude Code + AI-Agent-Backtester")


def load_walk_forward(path: Path) -> WalkForwardResult:
    """Rebuild a WalkForwardResult from the JSON written by docs/run_demo.py."""
    from datetime import date, datetime

    data = json.loads(path.read_text())
    folds = []
    for f in data["folds"]:
        fd = {k: (date.fromisoformat(v) if k != "index" else v) for k, v in f["fold"].items()}
        trades = [Trade(**{**t, "close_time": datetime.fromisoformat(t["close_time"])}) for t in f["oos_trades"]]
        folds.append(FoldResult(Fold(**fd), f["best_params"], f["is_metrics"], f["oos_summary"], trades))
    return WalkForwardResult(folds, data["initial_deposit"], data["criterion"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--stats", required=True)
    ap.add_argument("--opt", required=True)
    ap.add_argument("--wf")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    rep = parse_backtest_xlsx(Path(a.xlsx).read_bytes())
    stats = json.loads(Path(a.stats).read_text())
    opt = parse_optimization_xml(Path(a.opt).read_bytes())
    yearly = rep.yearly_returns()

    plot_equity(rep, str(OUT / "equity.png"),
                title="Moving Average (MetaQuotes example) · EURUSD H1 · 2020–2025 · open prices")
    opt.title = "Moving Average · EURUSD H1 · 2020–2025"
    plot_heatmap(opt, "MovingPeriod", "MovingShift", str(OUT / "heatmap.png"))
    term_backtest(stats, yearly)
    term_optimize(opt)
    agent_session(stats, yearly, opt)
    if a.wf:
        plot_walk_forward(load_walk_forward(Path(a.wf)), str(OUT / "walkforward.png"))
    print("images written to", OUT)


if __name__ == "__main__":
    main()
