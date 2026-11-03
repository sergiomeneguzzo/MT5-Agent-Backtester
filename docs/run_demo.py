"""Run the full README demo against a live terminal and save the raw outputs.

    python docs/run_demo.py demo_output/
    python docs/make_images.py --xlsx demo_output/backtest.xlsx --stats demo_output/stats.json \
        --opt demo_output/optimization.xml --wf demo_output/walkforward.json

Uses only MetaQuotes' bundled "Moving Average" example EA. Nothing is traded.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from mt5agent import MT5Client, Range, Tester

EA = "Examples/Moving Average/Moving Average"
COMMON = {"symbol": "EURUSD", "timeframe": "H1", "model": "open prices", "deposit": 10_000, "leverage": 100}
GRID = {"MovingPeriod": Range(10, 100, 10), "MovingShift": Range(0, 10, 2)}


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    tester = Tester(MT5Client.connect())

    run = tester.backtest(EA, start="2020-01-01", end="2025-12-31", **COMMON)
    (out / "stats.json").write_text(json.dumps(run.stats, indent=1))
    (out / "backtest.xlsx").write_bytes(run.raw)
    print("backtest", run.summary())

    opt = tester.optimize(EA, start="2020-01-01", end="2025-12-31", inputs=GRID, **COMMON)
    (out / "optimization.xml").write_bytes(opt.raw)
    print("optimization", opt.passes, "passes")

    wf = tester.walk_forward(EA, start="2020-01-01", end="2026-01-01", inputs=GRID,
                             is_months=24, oos_months=12, min_trades=100, **COMMON,
                             on_fold=lambda f: print(f.fold.label(), f.best_params,
                                                     f.oos_summary.get("profit_factor")))
    (out / "walkforward.json").write_text(json.dumps({
        "initial_deposit": wf.initial_deposit, "criterion": wf.criterion, "summary": wf.summary(),
        "folds": [{"fold": f.fold.__dict__, "best_params": f.best_params, "is_metrics": f.is_metrics,
                   "oos_summary": f.oos_summary,
                   "oos_trades": [t.__dict__ for t in f.oos_trades]} for f in wf.folds],
    }, indent=1, default=str))
    print("walk-forward", wf.summary())


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "demo_output"))
