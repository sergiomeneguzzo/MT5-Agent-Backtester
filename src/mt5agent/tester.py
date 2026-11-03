from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .client import MT5Client
from .config import DEFAULT_DEPOSIT, DEFAULT_LEVERAGE, DEFAULT_MODEL, FILE_PREFIX
from .errors import MT5Error
from .inputs import Range, grid_size, to_set_lines
from .reports import BacktestReport, OptimizationResult, parse_backtest_xlsx, parse_optimization_xml
from .walkforward import FoldResult, WalkForwardResult, make_folds

MODELS = ("every tick", "m1 ohlc", "open prices", "real ticks", "math calculations")
CRITERIA = {
    "balance": "balance_max",
    "profit_factor": "profit_factor_max",
    "expected_payoff": "expected_payoff_max",
    "drawdown": "drawdown_min",
    "recovery_factor": "recovery_factor_max",
    "sharpe": "sharpe_ratio_max",
    "custom": "custom_max",
}
SELECT_TO_CRITERION = {
    "Profit Factor": "profit_factor",
    "Profit": "balance",
    "Recovery Factor": "recovery_factor",
    "Sharpe Ratio": "sharpe",
}
GENETIC_THRESHOLD = 10_000
WAIT_CHUNK = 600

DateLike = str | date | datetime


@dataclass
class BacktestRun:
    run_id: str
    config: dict
    stats: dict
    report: BacktestReport | None
    seconds: float = 0.0
    raw: bytes = b""

    def summary(self) -> dict:
        keys = ("profit", "profit_factor", "trades", "drawdown_percent_equity",
                "recovery_factor", "sharpe_ratio", "expected_payoff")
        return {**{k: self.stats.get(k) for k in keys}, "seconds": round(self.seconds, 1)}


@dataclass
class OptimizationRun:
    run_id: str
    config: dict
    result: OptimizationResult
    seconds: float = 0.0
    raw: bytes = b""
    passes: int = field(init=False)

    def __post_init__(self) -> None:
        self.passes = len(self.result.passes)


class Tester:
    def __init__(self, client: MT5Client, *, prefix: str = FILE_PREFIX,
                 keep_files: bool = False, close_charts: bool = True):
        self.mt5 = client
        self.prefix = prefix
        self.keep_files = keep_files
        self.close_charts = close_charts
        self._defaults: dict[str, dict[str, str]] = {}

    def experts(self, filter: str = "") -> list[dict]:
        reply = self.mt5.call("list_available_mql5_programs", {"filter": filter, "program_type": "expert"})
        return reply.get("programs", [])

    def expert_inputs(self, expert: str) -> dict:
        return self.mt5.call("get_expert_advisor_parameters", {"expert_path": self.expert_path(expert)})

    def default_inputs(self, expert: str) -> dict[str, str]:
        path = self.expert_path(expert)
        if path not in self._defaults:
            parameters = self.expert_inputs(expert).get("parameters", [])
            self._defaults[path] = {p["name"]: p["value"] for p in parameters if p.get("type") != "group"}
        return dict(self._defaults[path])

    def expert_path(self, expert: str) -> str:
        if ":" in expert:
            return expert
        relative = expert.replace("/", "\\").strip("\\")
        if not relative.lower().endswith(".ex5"):
            relative += ".ex5"
        return self.mt5.mql5_path("Experts", relative)

    def backtest(self, expert: str, symbol: str, timeframe: str, start: DateLike, end: DateLike, *,
                 inputs: Mapping[str, Any] | None = None, model: str = DEFAULT_MODEL,
                 deposit: float = DEFAULT_DEPOSIT, leverage: int = DEFAULT_LEVERAGE,
                 currency: str | None = None, delay_ms: int | None = None,
                 detailed: bool = True, timeout: float = 3600) -> BacktestRun:
        if any(isinstance(v, Range) for v in (inputs or {}).values()):
            raise ValueError("inputs contain Range(); use optimize() instead")
        started = time.monotonic()
        config = self._config(expert, symbol, timeframe, start, end, model, deposit, leverage,
                              deposit_currency=currency, execution_delay=delay_ms)
        with self._job(symbol) as temp:
            run_id = self._run("tester_run_backtest", expert, config, inputs, temp, timeout)
            stats = self.mt5.call("tester_get_report", {"run_id": run_id})
            raw = self._download_report(run_id, "xlsx", temp) if detailed else b""
        report = parse_backtest_xlsx(raw) if raw else None
        return BacktestRun(run_id, {**config, "inputs": dict(inputs or {})}, stats, report,
                           time.monotonic() - started, raw)

    def optimize(self, expert: str, symbol: str, timeframe: str, start: DateLike, end: DateLike, *,
                 inputs: Mapping[str, Any], criterion: str = "profit_factor", genetic: bool | None = None,
                 model: str = DEFAULT_MODEL, deposit: float = DEFAULT_DEPOSIT,
                 leverage: int = DEFAULT_LEVERAGE, timeout: float = 7200) -> OptimizationRun:
        combinations = grid_size(inputs)
        if combinations <= 1:
            raise ValueError("optimize() needs at least one Range() input")
        started = time.monotonic()
        config = self._config(expert, symbol, timeframe, start, end, model, deposit, leverage,
                              optimization=True,
                              genetic=combinations > GENETIC_THRESHOLD if genetic is None else genetic,
                              optimization_criterion=CRITERIA.get(criterion, criterion))
        with self._job(symbol) as temp:
            run_id = self._run("tester_run_optimization", expert, config, inputs, temp, timeout)
            raw = self._download_report(run_id, "xml", temp)
        config["inputs"] = {k: (vars(v) if isinstance(v, Range) else v) for k, v in inputs.items()}
        config["grid_size"] = combinations
        params = [name for name, value in inputs.items() if isinstance(value, Range)]
        result = parse_optimization_xml(raw, params=params)
        return OptimizationRun(run_id, config, result, time.monotonic() - started, raw)

    def walk_forward(self, expert: str, symbol: str, timeframe: str, start: DateLike, end: DateLike, *,
                     inputs: Mapping[str, Any], is_months: int = 24, oos_months: int = 6,
                     anchored: bool = False, select_by: str = "Profit Factor", min_trades: int = 30,
                     model: str = DEFAULT_MODEL, deposit: float = DEFAULT_DEPOSIT,
                     leverage: int = DEFAULT_LEVERAGE,
                     on_fold: Callable[[FoldResult], None] | None = None) -> WalkForwardResult:
        fixed = {k: v for k, v in inputs.items() if not isinstance(v, Range)}
        common = {"model": model, "deposit": deposit, "leverage": leverage}
        results = []
        for fold in make_folds(_to_date(start), _to_date(end), is_months, oos_months, anchored):
            opt = self.optimize(expert, symbol, timeframe, fold.is_start, fold.is_end, inputs=inputs,
                                criterion=SELECT_TO_CRITERION.get(select_by, "profit_factor"), **common)
            best = opt.result.best(by=select_by, min_trades=min_trades)
            params = {name: best[name] for name in opt.result.params}
            oos = self.backtest(expert, symbol, timeframe, fold.oos_start, fold.oos_end,
                                inputs={**fixed, **params}, **common)
            result = FoldResult(fold, params, best,
                                oos.report.summary() if oos.report else {},
                                oos.report.trades if oos.report else [])
            results.append(result)
            if on_fold:
                on_fold(result)
        return WalkForwardResult(results, deposit, select_by)

    def _config(self, expert: str, symbol: str, timeframe: str, start: DateLike, end: DateLike,
                model: str, deposit: float, leverage: int, optimization: bool = False, **extra: Any) -> dict:
        if model not in MODELS:
            raise ValueError(f"model must be one of {MODELS}")
        config = {
            "mql5_program_path": self.expert_path(expert),
            "symbol": symbol,
            "timeframe": timeframe.upper(),
            "model": model,
            "from_date": _to_iso(start),
            "to_date": _to_iso(end),
            "deposit": deposit,
            "leverage": leverage,
            "optimization": optimization,
        }
        config.update({k: v for k, v in extra.items() if v is not None})
        return config

    def _run(self, tool: str, expert: str, config: dict, inputs: Mapping[str, Any] | None,
             temp: list[str], timeout: float) -> str:
        ini = self._temp_path("ini", temp)
        set_file = self._temp_path("set", temp)
        self.mt5.call("tester_prepare_config", {**config, "output_path": ini})
        self.mt5.call("tester_prepare_inputs", {"mql5_program_path": config["mql5_program_path"],
                                                "parameters": to_set_lines({**self.default_inputs(expert),
                                                                            **(inputs or {})}),
                                                "output_path": set_file})
        args = {"config_path": ini, "inputs_path": set_file, "wait": True,
                "timeout_sec": int(min(timeout, WAIT_CHUNK))}
        reply = self.mt5.call(tool, args)
        return self._wait(reply, timeout)

    def _wait(self, reply: dict, timeout: float) -> str:
        run_id = reply["run_id"]
        deadline = time.monotonic() + timeout
        while reply.get("timed_out"):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.mt5.call("tester_stop", {"run_id": run_id})
                raise TimeoutError(f"Tester run {run_id} exceeded {timeout:.0f}s and was stopped")
            reply = self.mt5.call("tester_wait", {"run_id": run_id, "timeout_sec": int(min(remaining, WAIT_CHUNK))})
        return run_id

    def _download_report(self, run_id: str, extension: str, temp: list[str]) -> bytes:
        path = self._temp_path(extension, temp, folder=("Files",))
        self.mt5.call("tester_get_report", {"run_id": run_id, "file_format": "xml", "path": path})
        return self.mt5.read_bytes(path)

    def _temp_path(self, extension: str, temp: list[str], folder: tuple[str, ...] = ("Profiles", "Tester")) -> str:
        path = self.mt5.mql5_path(*folder, f"{self.prefix}_{uuid.uuid4().hex[:10]}.{extension}")
        temp.append(path)
        return path

    @contextmanager
    def _job(self, symbol: str) -> Iterator[list[str]]:
        charts_before = self._chart_ids() if self.close_charts else None
        temp: list[str] = []
        try:
            yield temp
        finally:
            if not self.keep_files:
                for path in temp:
                    self._try("delete_file", {"path": path})
            if charts_before is not None:
                self.close_new_charts(charts_before, symbol)

    def close_new_charts(self, existing: set[str], symbol: str) -> int:
        closed = 0
        for chart in self._charts() or []:
            chart_id = _chart_id(chart)
            if chart_id and chart_id not in existing and _is_tester_chart(chart, symbol):
                closed += self._try("chart_close", {"chart_id": chart_id})
        return closed

    def _charts(self) -> list[dict] | None:
        try:
            return self.mt5.call("list_open_charts").get("charts", [])
        except MT5Error:
            return None

    def _chart_ids(self) -> set[str] | None:
        charts = self._charts()
        return None if charts is None else {_chart_id(c) for c in charts}

    def _try(self, tool: str, args: dict) -> bool:
        try:
            self.mt5.call(tool, args)
            return True
        except MT5Error:
            return False


def _chart_id(chart: dict) -> str:
    return str(chart.get("chart_id", chart.get("id", "")))


PROGRAM_KEYS = ("expert", "robot", "script")


def _is_tester_chart(chart: dict, symbol: str) -> bool:
    if chart.get("symbol") != symbol:
        return False
    return not any(value and key.lower().split("_")[0].rstrip("s") in PROGRAM_KEYS for key, value in chart.items())


def _to_date(value: DateLike) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value[:10])


def _to_iso(value: DateLike) -> str:
    return f"{_to_date(value).isoformat()}T00:00:00"
