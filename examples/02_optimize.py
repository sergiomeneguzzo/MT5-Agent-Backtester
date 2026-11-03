"""Grid-optimize two inputs and draw the profit-factor heatmap."""
from mt5agent import MT5Client, Range, Tester

tester = Tester(MT5Client.connect())

opt = tester.optimize(
    "Examples/Moving Average/Moving Average",
    symbol="EURUSD", timeframe="H1",
    start="2020-01-01", end="2025-12-31",
    inputs={
        "MaximumRisk": 0.02,                       # fixed
        "MovingPeriod": Range(10, 100, 10),        # optimized
        "MovingShift": Range(0, 10, 2),            # optimized
    },
    criterion="profit_factor",
)

res = opt.result
print(f"{opt.passes} passes in {opt.seconds:.0f}s, optimized: {res.params}")
print("best (in-sample!):", res.best(by="Profit Factor", min_trades=200))

df = res.to_dataframe()                            # needs pandas
print(df.sort_values("Profit Factor", ascending=False).head(10))

from mt5agent.plots import plot_heatmap  # noqa: E402

plot_heatmap(res, "MovingPeriod", "MovingShift", "heatmap.png")
