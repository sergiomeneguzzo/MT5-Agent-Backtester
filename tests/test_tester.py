from datetime import date

import pytest

from mt5agent import Range, Tester, TradingBlockedError
from mt5agent.inputs import grid_size, parse_assignments, to_set_lines
from mt5agent.walkforward import make_folds


# -- client safety ---------------------------------------------------------
def test_handshake_calls_workspace_first(client, fake):
    assert fake.calls[0][0] == "get_workspace_info"
    assert client.mql5_folder == r"C:\MT5\MQL5"


def test_trade_tools_are_blocked_and_hidden(client):
    with pytest.raises(TradingBlockedError):
        client.call("trade_send_market_order", {"symbol": "EURUSD"})
    assert "trade_send_market_order" not in [t["name"] for t in client.tools()]


def test_settings_repr_hides_key(client):
    assert "test-key" not in repr(client.settings)


# -- inputs ----------------------------------------------------------------
def test_set_lines():
    lines = to_set_lines({"Period": Range(10, 50, 10), "Risk": 0.5, "Use": True, "N": 3.0})
    assert lines == ["Period=10||10||10||50||Y", "Risk=0.5", "Use=true", "N=3"]
    assert grid_size({"a": Range(1, 3, 1), "b": Range(0, 1, 0.5), "c": 7}) == 9


def test_cli_param_parsing():
    p = parse_assignments(["A=1:5:2", "B=0.25", "C=false", "D=text"])
    assert p["A"] == Range(1, 5, 2) and p["B"] == 0.25 and p["C"] is False and p["D"] == "text"


# -- tester ----------------------------------------------------------------
def test_backtest_flow(client, fake, sample_xlsx):
    fake.report_bytes = sample_xlsx
    run = Tester(client).backtest("Examples/Moving Average/Moving Average", "EURUSD", "h1",
                                  "2020-01-01", "2021-12-31", inputs={"MovingPeriod": 20})
    names = [n for n, _ in fake.calls]
    assert names.index("tester_prepare_config") < names.index("tester_run_backtest")
    cfg = dict(fake.calls)["tester_prepare_config"]
    assert cfg["mql5_program_path"] == r"C:\MT5\MQL5\Experts\Examples\Moving Average\Moving Average.ex5"
    assert cfg["timeframe"] == "H1" and cfg["from_date"] == "2020-01-01T00:00:00"
    assert dict(fake.calls)["tester_prepare_inputs"]["parameters"] == ["MovingPeriod=20"]
    assert run.stats["profit_factor"] == pytest.approx(0.8815)
    assert len(run.report.trades) == 2
    # temp .ini/.set/.xlsx are cleaned up
    deleted = [a["path"] for n, a in fake.calls if n == "delete_file"]
    assert {p.rsplit(".", 1)[1] for p in deleted} == {"ini", "set", "xlsx"}


def test_backtest_rejects_ranges(client):
    with pytest.raises(ValueError):
        Tester(client).backtest("X", "EURUSD", "H1", "2020-01-01", "2021-01-01",
                                inputs={"P": Range(1, 2, 1)})


def test_long_run_keeps_waiting(client, fake, sample_xlsx):
    fake.report_bytes = sample_xlsx
    fake.wait_rounds = 2
    Tester(client).backtest("X", "EURUSD", "H1", "2020-01-01", "2021-01-01")
    assert [n for n, _ in fake.calls].count("tester_wait") == 2


def test_only_new_bare_charts_are_closed(client, fake, sample_xlsx):
    fake.report_bytes = sample_xlsx
    fake.charts = [{"chart_id": "1", "symbol": "XAUUSD", "experts": [{"name": "LiveEA"}]},
                   {"chart_id": "2", "symbol": "EURUSD", "experts": [], "indicators": []}]
    fake.charts_after_run = [{"chart_id": "3", "symbol": "EURUSD", "experts": [], "indicators": []},
                             {"chart_id": "4", "symbol": "EURUSD", "experts": [{"name": "X"}]}]
    Tester(client).backtest("X", "EURUSD", "H1", "2020-01-01", "2021-01-01")
    closed = [a["chart_id"] for n, a in fake.calls if n == "chart_close"]
    assert closed == ["3"]          # pre-existing (1, 2) and EA charts (4) untouched


def test_optimize_flow(client, fake, optimization_xml):
    fake.report_bytes = optimization_xml
    run = Tester(client).optimize("X", "EURUSD", "H1", "2020-01-01", "2025-12-31",
                                  inputs={"MovingPeriod": Range(10, 100, 10), "MovingShift": Range(0, 10, 2)})
    cfg = dict(fake.calls)["tester_prepare_config"]
    assert cfg["optimization"] is True and cfg["genetic"] is False
    assert cfg["optimization_criterion"] == "profit_factor_max"
    assert run.passes == 60 and run.config["grid_size"] == 60


def test_optimize_needs_a_range(client):
    with pytest.raises(ValueError):
        Tester(client).optimize("X", "EURUSD", "H1", "2020-01-01", "2021-01-01", inputs={"P": 1})


# -- walk-forward ------------------------------------------------------------
def test_rolling_folds_tile_the_period():
    folds = make_folds(date(2020, 1, 1), date(2026, 1, 1), is_months=24, oos_months=12)
    assert [(f.is_start.year, f.oos_start.year, f.oos_end.year) for f in folds] == [
        (2020, 2022, 2023), (2021, 2023, 2024), (2022, 2024, 2025), (2023, 2025, 2026)]
    for a, b in zip(folds, folds[1:]):
        assert a.oos_end == b.oos_start


def test_anchored_folds_keep_start():
    folds = make_folds(date(2020, 1, 1), date(2023, 1, 1), is_months=12, oos_months=6, anchored=True)
    assert all(f.is_start == date(2020, 1, 1) for f in folds)
    assert folds[-1].oos_end == date(2023, 1, 1)


def test_walk_forward_end_to_end(client, fake, optimization_xml, sample_xlsx, monkeypatch):
    tester = Tester(client)
    reports = iter([optimization_xml, sample_xlsx] * 10)

    def next_report(name, args):
        if name == "tester_get_report" and "path" in args:
            fake.report_bytes = next(reports)
        return original(name, args)

    original = fake.tool
    monkeypatch.setattr(fake, "tool", next_report)
    wf = tester.walk_forward("X", "EURUSD", "H1", "2020-01-01", "2022-01-01",
                             inputs={"MaximumRisk": 0.02, "MovingPeriod": Range(10, 100, 10),
                                     "MovingShift": Range(0, 10, 2)},
                             is_months=12, oos_months=6, min_trades=0)
    assert len(wf.folds) == 2
    assert wf.folds[0].best_params == {"MovingPeriod": 80, "MovingShift": 6}
    oos_inputs = [a["parameters"] for n, a in fake.calls if n == "tester_prepare_inputs"][1]
    assert oos_inputs == ["MaximumRisk=0.02", "MovingPeriod=80", "MovingShift=6"]
    s = wf.summary()
    assert s["folds"] == 2 and s["trades"] == 4


def test_no_chart_is_closed_when_the_first_snapshot_fails(client, fake, sample_xlsx, monkeypatch):
    from mt5agent.errors import MT5Error

    fake.report_bytes = sample_xlsx
    fake.charts = [{"chart_id": "1", "symbol": "EURUSD", "experts": [], "indicators": []}]
    original, calls = fake.tool, {"n": 0}

    def flaky(name, args):
        if name == "list_open_charts":
            calls["n"] += 1
            if calls["n"] == 1:
                raise MT5Error("temporary failure")
        return original(name, args)

    monkeypatch.setattr(fake, "tool", flaky)
    try:
        Tester(client).backtest("X", "EURUSD", "H1", "2020-01-01", "2021-01-01")
    except MT5Error:
        pass
    assert "chart_close" not in [n for n, _ in fake.calls]
