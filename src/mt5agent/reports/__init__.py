from .backtest import BacktestReport, Deal, Trade, parse_backtest_xlsx
from .optimization import OptimizationResult, parse_optimization_xml


def parse_report(data: bytes) -> BacktestReport | OptimizationResult:
    return parse_backtest_xlsx(data) if data[:2] == b"PK" else parse_optimization_xml(data)


__all__ = [
    "BacktestReport", "Deal", "OptimizationResult", "Trade",
    "parse_backtest_xlsx", "parse_optimization_xml", "parse_report",
]
