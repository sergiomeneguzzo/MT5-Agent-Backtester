from __future__ import annotations

from collections.abc import Iterable, Sequence


def profit_factor(pnl: Iterable[float]) -> float:
    pnl = list(pnl)
    gross_win = sum(p for p in pnl if p > 0)
    gross_loss = -sum(p for p in pnl if p < 0)
    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss


def max_drawdown(balances: Sequence[float]) -> tuple[float, float]:
    peak, worst_abs, worst_pct = float("-inf"), 0.0, 0.0
    for balance in balances:
        peak = max(peak, balance)
        if peak > 0:
            worst_abs = max(worst_abs, peak - balance)
            worst_pct = max(worst_pct, (peak - balance) / peak * 100)
    return worst_abs, worst_pct


def yearly_returns(trades, initial_deposit: float) -> dict[int, float]:
    returns: dict[int, float] = {}
    balance = year_open = initial_deposit
    year = None
    for trade in trades:
        if year is not None and trade.close_time.year != year:
            returns[year] = _pct(balance - year_open, year_open)
            year_open = balance
        year = trade.close_time.year
        balance += trade.net
    if year is not None:
        returns[year] = _pct(balance - year_open, year_open)
    return returns


def summarize(trades, initial_deposit: float) -> dict:
    pnl = [t.net for t in trades]
    balances = [initial_deposit]
    for p in pnl:
        balances.append(balances[-1] + p)
    dd_abs, dd_pct = max_drawdown(balances)
    net = sum(pnl)
    count = len(pnl)
    return {
        "trades": count,
        "net_profit": round(net, 2),
        "return_pct": round(_pct(net, initial_deposit), 2) if initial_deposit else None,
        "profit_factor": round(profit_factor(pnl), 3),
        "win_rate_pct": round(_pct(sum(p > 0 for p in pnl), count), 2) if count else 0.0,
        "avg_trade": round(net / count, 2) if count else 0.0,
        "max_dd": round(dd_abs, 2),
        "max_dd_pct": round(dd_pct, 2),
        "recovery_factor": round(net / dd_abs, 3) if dd_abs else None,
    }


def _pct(part: float, whole: float) -> float:
    return part / whole * 100 if whole else 0.0
