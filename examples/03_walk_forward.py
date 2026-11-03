"""Rolling walk-forward: 2 years in-sample -> 1 year out-of-sample, 2020-2025."""
from mt5agent import MT5Client, Range, Tester

tester = Tester(MT5Client.connect())

wf = tester.walk_forward(
    "Examples/Moving Average/Moving Average",
    symbol="EURUSD", timeframe="H1",
    start="2020-01-01", end="2026-01-01",
    inputs={"MovingPeriod": Range(10, 100, 10), "MovingShift": Range(0, 10, 2)},
    is_months=24, oos_months=12,
    select_by="Profit Factor", min_trades=100,
    on_fold=lambda f: print(f.fold.label(), f.best_params, f.oos_summary["profit_factor"]),
)

print(wf.summary())

from mt5agent.plots import plot_walk_forward  # noqa: E402

plot_walk_forward(wf, "walkforward.png")
