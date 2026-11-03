# Backtesting rules for this project

You can run MetaTrader 5 backtests through the `mt5-backtester` MCP server.

- Use `run_backtest` for a single run, `run_optimization` to explore inputs and
  `run_walk_forward` before calling any result "robust". The best pass of an
  optimization is in-sample and does not count as evidence on its own.
- Default to `model: "open prices"` for exploration and confirm final numbers with
  `"real ticks"` (or `"every tick"` if real ticks are not available).
- Report profit factor, max equity drawdown, number of trades and yearly returns.
  Flag anything with fewer than 100 trades as statistically weak.
- There are no trading tools. Never ask for them.
