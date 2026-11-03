from ._version import __version__
from .client import MT5Client
from .config import Settings
from .errors import MT5Error, TradingBlockedError
from .inputs import Range
from .reports import BacktestReport, OptimizationResult, parse_backtest_xlsx, parse_optimization_xml, parse_report
from .tester import BacktestRun, OptimizationRun, Tester
from .walkforward import WalkForwardResult, make_folds

__all__ = [
    "BacktestReport", "BacktestRun", "MT5Client", "MT5Error", "OptimizationResult", "OptimizationRun",
    "Range", "Settings", "Tester", "TradingBlockedError", "WalkForwardResult", "__version__",
    "make_folds", "parse_backtest_xlsx", "parse_optimization_xml", "parse_report",
]
