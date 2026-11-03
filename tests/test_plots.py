from datetime import date, datetime

import pytest

pytest.importorskip("matplotlib")

from mt5agent.plots import plot_equity, plot_heatmap, plot_walk_forward  # noqa: E402
from mt5agent.reports import Trade, parse_backtest_xlsx, parse_optimization_xml  # noqa: E402
from mt5agent.walkforward import FoldResult, WalkForwardResult, make_folds  # noqa: E402


def _png(path):
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 5_000


def test_equity_png(sample_xlsx, tmp_path):
    out = tmp_path / "eq.png"
    plot_equity(parse_backtest_xlsx(sample_xlsx), str(out))
    _png(out)


def test_heatmap_png(optimization_xml, tmp_path):
    out = tmp_path / "hm.png"
    plot_heatmap(parse_optimization_xml(optimization_xml), "MovingPeriod", "MovingShift", str(out))
    _png(out)


def test_walk_forward_png(tmp_path):
    folds = make_folds(date(2020, 1, 1), date(2023, 1, 1), 12, 12)
    results = []
    for k, f in enumerate(folds):
        trades = [Trade(datetime(f.oos_start.year, m, 15), "EURUSD", "long", 0.1, 1.1,
                        (25.0 if k == 0 else -10.0) * (1 if m % 3 else -1), 0) for m in range(1, 13)]
        results.append(FoldResult(f, {"MovingPeriod": 50 + 10 * k}, {"Profit": 900.0},
                                  {"net_profit": sum(t.net for t in trades)}, trades))
    wf = WalkForwardResult(results, 10_000, "Profit Factor")
    assert wf.summary()["folds"] == 2 and wf.summary()["profitable_folds"] == 1
    out = tmp_path / "wf.png"
    plot_walk_forward(wf, str(out))
    _png(out)
