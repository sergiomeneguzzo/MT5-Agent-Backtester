"""High-level Strategy Tester API on top of the MT5 MCP server.

    from mt5agent import MT5Client, Tester, Range

    tester = Tester(MT5Client.connect())
    run = tester.backtest("Examples/Moving Average/Moving Average",
                          symbol="EURUSD", timeframe="H1",
                          start="2020-01-01", end="2025-12-31")
    print(run.stats["profit_factor"], len(run.report.trades))
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .client import MT5Client, MT5Error
from .inputs import Range, grid_size, to_set_lines
from .report import BacktestReport, OptimizationResult, parse_backtest_xlsx, parse_optimization_xml
from .walkforward import FoldResult, WalkForwardResult, make_folds

MODELS = ("every tick", "m1 ohlc", "open prices", "real ticks", "math calculations")
CRITERIA = {
    "balance": "balance_max", "profit_factor": "profit_factor_max",
    "expected_payoff": "expected_payoff_max", "drawdown": "drawdown_min",
    "recovery_factor": "recovery_factor_max", "sharpe": "sharpe_ratio_max",
    "custom": "custom_max",
}


def _iso(d: str | date | datetime) -> str:
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%dT00:00:00")
    if isinstance(d, date):
        return d.strftime("%Y-%m-%dT00:00:00")
    return f"{d}T00:00:00" if len(d) == 10 else d


def _as_date(d: str | date | datetime) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(d[:10])


@dataclass
class BacktestRun:
    run_id: str
    config: dict
    stats: dict                      # MT5 JSON report: profit_factor, trades, drawdown ...
    report: BacktestReport | None    # full deal list (when detailed=True)
    seconds: float = 0.0
    raw: bytes = b""                 # the original .xlsx report, if downloaded

    def summary(self) -> dict:
        keys = ("profit", "profit_factor", "trades", "drawdown_percent_equity",
                "recovery_factor", "sharpe_ratio", "expected_payoff")
        out = {k: self.stats.get(k) for k in keys}
        out["seconds"] = round(self.seconds, 1)
        return out


@dataclass
class OptimizationRun:
    run_id: str
    config: dict
    result: OptimizationResult
    seconds: float = 0.0
    raw: bytes = b""                 # the original SpreadsheetML .xml
    passes: int = field(init=False)

    def __post_init__(self) -> None:
        self.passes = len(self.result.passes)


class Tester:
    __test__ = False  # not a pytest class
    """Runs Strategy Tester jobs and returns parsed, agent-friendly results."""

    def __init__(self, client: MT5Client, *, prefix: str = "mt5agent",
                 keep_files: bool = False, close_charts: bool = True) -> None:
        self.mt5 = client
        self.prefix = prefix
        self.keep_files = keep_files
        self.close_charts = close_charts

    # -- paths ------------------------------------------------------------
    def expert_path(self, expert: str) -> str:
        """Accept ``C:\\...\\X.ex5`` or a path relative to ``MQL5\\Experts`` (no extension)."""
        if ":" in expert:
            return expert
        rel = expert.replace("/", "\\").strip("\\")
        if not rel.lower().endswith(".ex5"):
            rel += ".ex5"
        return self.mt5.mql5_path("Experts", rel)

    def _tmp(self, ext: str, folder: tuple[str, ...] = ("Profiles", "Tester")) -> str:
        return self.mt5.mql5_path(*folder, f"{self.prefix}_{uuid.uuid4().hex[:10]}.{ext}")

    def _delete(self, *paths: str) -> None:
        if self.keep_files:
            return
        for p in paths:
            try:
                self.mt5.call("delete_file", {"path": p})
            except MT5Error:
                pass

    # -- discovery --------------------------------------------------------
    def experts(self, filter: str = "") -> list[dict]:
        reply = self.mt5.call("list_available_mql5_programs",
                              {"filter": filter, "program_type": "expert"})
        return reply.get("programs", [])

    def expert_inputs(self, expert: str) -> dict:
        return self.mt5.call("get_expert_advisor_parameters", {"expert_path": self.expert_path(expert)})

    # -- core -------------------------------------------------------------
    def _config(self, expert: str, symbol: str, timeframe: str, start, end, model: str,
                deposit: float, leverage: int, optimization: bool = False, **extra: Any) -> tuple[str, dict]:
        if model not in MODELS:
            raise ValueError(f"model must be one of {MODELS}")
        cfg = {
            "mql5_program_path": self.expert_path(expert), "symbol": symbol,
            "timeframe": timeframe.upper(), "model": model,
            "from_date": _iso(start), "to_date": _iso(end),
            "deposit": deposit, "leverage": leverage, "optimization": optimization,
        }
        cfg.update({k: v for k, v in extra.items() if v is not None})
        path = self._tmp("ini")
        self.mt5.call("tester_prepare_config", {**cfg, "output_path": path})
        return path, cfg

    def _inputs(self, expert: str, inputs: Mapping[str, Any] | None) -> str | None:
        if not inputs:
            return None
        path = self._tmp("set")
        self.mt5.call("tester_prepare_inputs", {"mql5_program_path": self.expert_path(expert),
                                                "parameters": to_set_lines(inputs),
                                                "output_path": path})
        return path

    def _run(self, tool: str, ini: str, set_: str | None, timeout: float) -> str:
        args = {"config_path": ini, "wait": True, "timeout_sec": int(min(timeout, 600))}
        if set_:
            args["inputs_path"] = set_
        reply = self.mt5.call(tool, args)
        run_id = reply["run_id"]
        deadline = time.monotonic() + timeout
        while reply.get("timed_out"):
            left = deadline - time.monotonic()
            if left <= 0:
                self.mt5.call("tester_stop", {"run_id": run_id})
                raise TimeoutError(f"Tester run {run_id} exceeded {timeout:.0f}s and was stopped")
            reply = self.mt5.call("tester_wait", {"run_id": run_id, "timeout_sec": int(min(left, 600))})
        return run_id

    def backtest(self, expert: str, symbol: str, timeframe: str, start, end, *,
                 inputs: Mapping[str, Any] | None = None, model: str = "open prices",
                 deposit: float = 10_000, leverage: int = 100, currency: str | None = None,
                 delay_ms: int | None = None, detailed: bool = True,
                 timeout: float = 3600) -> BacktestRun:
        """Run one backtest. ``detailed=True`` also downloads every deal."""
        if any(isinstance(v, Range) for v in (inputs or {}).values()):
            raise ValueError("inputs contain Range(); use optimize() instead")
        t0 = time.monotonic()
        before = {self._chart_id(c) for c in self._charts()} if self.close_charts else None
        ini, cfg = self._config(expert, symbol, timeframe, start, end, model, deposit, leverage,
                                deposit_currency=currency, execution_delay=delay_ms)
        set_ = self._inputs(expert, inputs)
        cfg["inputs"] = dict(inputs or {})
        try:
            run_id = self._run("tester_run_backtest", ini, set_, timeout)
            stats = self.mt5.call("tester_get_report", {"run_id": run_id})
            report, raw = None, b""
            if detailed:
                xlsx = self._tmp("xlsx", ("Files",))
                self.mt5.call("tester_get_report", {"run_id": run_id, "file_format": "xml", "path": xlsx})
                raw = self.mt5.read_bytes(xlsx)
                report = parse_backtest_xlsx(raw)
                self._delete(xlsx)
        finally:
            self._delete(*(p for p in (ini, set_) if p))
            if self.close_charts:
                self.cleanup_charts(opened_after=before)
        return BacktestRun(run_id, cfg, stats, report, time.monotonic() - t0, raw)

    def optimize(self, expert: str, symbol: str, timeframe: str, start, end, *,
                 inputs: Mapping[str, Any], criterion: str = "profit_factor",
                 genetic: bool | None = None, model: str = "open prices",
                 deposit: float = 10_000, leverage: int = 100,
                 timeout: float = 7200) -> OptimizationRun:
        """Optimize every input given as ``Range``; other inputs stay fixed."""
        n = grid_size(inputs)
        if n <= 1:
            raise ValueError("optimize() needs at least one Range() input")
        if genetic is None:
            genetic = n > 10_000
        t0 = time.monotonic()
        before = {self._chart_id(c) for c in self._charts()} if self.close_charts else None
        ini, cfg = self._config(expert, symbol, timeframe, start, end, model, deposit, leverage,
                                optimization=True, genetic=genetic,
                                optimization_criterion=CRITERIA.get(criterion, criterion))
        set_ = self._inputs(expert, inputs)
        cfg["inputs"] = {k: (v.__dict__ if isinstance(v, Range) else v) for k, v in inputs.items()}
        cfg["grid_size"] = n
        try:
            run_id = self._run("tester_run_optimization", ini, set_, timeout)
            xml = self._tmp("xml", ("Files",))
            self.mt5.call("tester_get_report", {"run_id": run_id, "file_format": "xml", "path": xml})
            raw = self.mt5.read_bytes(xml)
            result = parse_optimization_xml(raw)
            self._delete(xml)
        finally:
            self._delete(ini, set_)
            if self.close_charts:
                self.cleanup_charts(opened_after=before)
        return OptimizationRun(run_id, cfg, result, time.monotonic() - t0, raw)

    def walk_forward(self, expert: str, symbol: str, timeframe: str, start, end, *,
                     inputs: Mapping[str, Any], is_months: int = 24, oos_months: int = 6,
                     anchored: bool = False, select_by: str = "Profit Factor",
                     min_trades: int = 30, model: str = "open prices",
                     deposit: float = 10_000, leverage: int = 100,
                     on_fold=None) -> WalkForwardResult:
        """Optimize on each in-sample window, then trade the winner out-of-sample.

        The stitched OOS trades are what you would have got by re-optimizing on a
        schedule — the honest number, unlike the best pass of one big optimization.
        """
        crit = {"Profit Factor": "profit_factor", "Profit": "balance",
                "Recovery Factor": "recovery_factor", "Sharpe Ratio": "sharpe"}.get(select_by, "profit_factor")
        fixed = {k: v for k, v in inputs.items() if not isinstance(v, Range)}
        results: list[FoldResult] = []
        for fold in make_folds(_as_date(start), _as_date(end), is_months, oos_months, anchored):
            opt = self.optimize(expert, symbol, timeframe, fold.is_start, fold.is_end,
                                inputs=inputs, criterion=crit, model=model,
                                deposit=deposit, leverage=leverage)
            best = opt.result.best(by=select_by, min_trades=min_trades)
            params = {p: best[p] for p in opt.result.params}
            oos = self.backtest(expert, symbol, timeframe, fold.oos_start, fold.oos_end,
                                inputs={**fixed, **params}, model=model,
                                deposit=deposit, leverage=leverage)
            trades = oos.report.trades if oos.report else []
            fr = FoldResult(fold, params, best, oos.report.summary() if oos.report else {}, trades)
            results.append(fr)
            if on_fold:
                on_fold(fr)
        return WalkForwardResult(results, deposit, select_by)

    # -- hygiene ----------------------------------------------------------
    def _charts(self) -> list[dict]:
        try:
            return self.mt5.call("list_open_charts").get("charts", [])
        except MT5Error:
            return []

    @staticmethod
    def _chart_id(chart: dict) -> str:
        return str(chart.get("chart_id", chart.get("id", "")))

    @staticmethod
    def _is_bare(chart: dict) -> bool:
        """True only if nothing at all is attached (no EA, robot, script or indicator)."""
        for key, value in chart.items():
            k = key.lower()
            if any(w in k for w in ("expert", "robot", "indicator", "script")) and value:
                return False
        return True

    def cleanup_charts(self, opened_after: set[str] | None = None) -> int:
        """Close bare charts the Strategy Tester opened during our run.

        Only charts that were *not* open before the run (``opened_after`` is the
        snapshot of ids taken before it) and have nothing attached are closed, so
        live charts running an EA are never touched. Returns how many were closed.
        """
        if opened_after is None:
            return 0
        closed = 0
        for chart in self._charts():
            cid = self._chart_id(chart)
            if cid and cid not in opened_after and self._is_bare(chart):
                try:
                    self.mt5.call("chart_close", {"chart_id": cid})
                    closed += 1
                except MT5Error:
                    pass
        return closed
