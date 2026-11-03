from datetime import datetime

import pytest

from mt5agent.metrics import max_drawdown, profit_factor, yearly_returns
from mt5agent.report import parse_backtest_xlsx, parse_optimization_xml


def test_backtest_header_and_inputs(sample_xlsx):
    rep = parse_backtest_xlsx(sample_xlsx)
    assert rep.expert == "Moving Average"
    assert rep.symbol == "EURUSD"
    assert rep.inputs == {"MovingPeriod": "12", "MovingShift": "6"}
    assert rep.metric("Profit Factor") == pytest.approx(1.75)
    assert rep.metric("Total Net Profit") == pytest.approx(150.0)


def test_private_fields_are_dropped_by_default(sample_xlsx):
    rep = parse_backtest_xlsx(sample_xlsx)
    assert "server" not in rep.settings and "company" not in rep.settings
    kept = parse_backtest_xlsx(sample_xlsx, keep_private=True)
    assert kept.settings["company"] == "Some Broker Ltd"
    assert kept.settings["server"].startswith("Some-Broker-Server")


def test_deals_and_trades(sample_xlsx):
    rep = parse_backtest_xlsx(sample_xlsx)
    assert len(rep.deals) == 5                         # totals line skipped
    assert rep.initial_deposit == 10000
    trades = rep.trades
    assert [t.side for t in trades] == ["long", "short"]
    assert trades[0].net == pytest.approx(200 - 0.5 - 0.5 - 1.0)   # both commissions + swap
    assert trades[1].net == pytest.approx(-51.0)
    assert trades[0].close_time == datetime(2020, 3, 3, 10)


def test_summary_matches_balance(sample_xlsx):
    rep = parse_backtest_xlsx(sample_xlsx)
    s = rep.summary()
    assert s["trades"] == 2
    assert s["net_profit"] == pytest.approx(147.0)
    assert 10000 + s["net_profit"] == pytest.approx(rep.deals[-1].balance)
    assert s["profit_factor"] == pytest.approx(197.5 / 50.5 * 1, rel=1e-2)


def test_equity_curve_excludes_entries(sample_xlsx):
    curve = parse_backtest_xlsx(sample_xlsx).equity_curve()
    assert [b for _, b in curve] == [10000.0, 10198.0, 10147.0]


def test_yearly_returns(sample_xlsx):
    rep = parse_backtest_xlsx(sample_xlsx)
    yr = yearly_returns(rep.trades, rep.initial_deposit)
    assert list(yr) == [2020, 2021]
    assert yr[2020] == pytest.approx(1.98)
    assert yr[2021] == pytest.approx(-51 / 10198 * 100)


def test_optimization_xml(optimization_xml):
    res = parse_optimization_xml(optimization_xml)
    assert res.params == ["MovingPeriod", "MovingShift"]
    assert len(res.passes) == 60
    best = res.best("Profit Factor")
    assert best["MovingPeriod"] == 80 and best["MovingShift"] == 6
    assert isinstance(best["Trades"], int)
    assert best["Profit Factor"] == pytest.approx(1.153186)


def test_best_respects_min_trades(optimization_xml):
    res = parse_optimization_xml(optimization_xml)
    assert res.best(min_trades=900)["Trades"] >= 900
    with pytest.raises(ValueError):
        res.best(min_trades=10**9)


def test_metrics_edge_cases():
    assert profit_factor([]) == 0.0
    assert profit_factor([5, 5]) == float("inf")
    assert max_drawdown([100, 120, 90, 130]) == (30, 25.0)
