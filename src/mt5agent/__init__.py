"""mt5-agent-backtester: let AI agents (and you) run MetaTrader 5 backtests from code."""
__version__ = "0.1.0"

from .client import MT5Client, MT5Error, TradingBlockedError
from .inputs import Range
from .report import BacktestReport, OptimizationResult, parse_backtest_xlsx, parse_optimization_xml
from .tester import BacktestRun, OptimizationRun, Tester
from .walkforward import WalkForwardResult, make_folds

__all__ = [
    "BacktestReport", "BacktestRun", "MT5Client", "MT5Error", "OptimizationResult",
    "OptimizationRun", "Range", "Tester", "TradingBlockedError", "WalkForwardResult",
    "__version__", "make_folds", "parse_backtest_xlsx", "parse_optimization_xml",
]
