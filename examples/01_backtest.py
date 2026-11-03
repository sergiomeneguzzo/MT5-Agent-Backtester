"""Run one backtest of the Moving Average EA that ships with every MT5 install."""
from mt5agent import MT5Client, Tester

tester = Tester(MT5Client.connect())

run = tester.backtest(
    "Examples/Moving Average/Moving Average",
    symbol="EURUSD", timeframe="H1",
    start="2020-01-01", end="2025-12-31",
    model="open prices", deposit=10_000, leverage=100,
    inputs={"MovingPeriod": 12, "MovingShift": 6},
)

print(run.summary())
rep = run.report
print(len(rep.trades), "closed trades, first:", rep.trades[0])
for year, ret in rep.yearly_returns().items():
    print(year, f"{ret:+.2f}%")

from mt5agent.plots import plot_equity  # noqa: E402

plot_equity(rep, "equity.png")
