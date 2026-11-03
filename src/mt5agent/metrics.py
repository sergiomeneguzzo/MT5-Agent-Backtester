"""Small, dependency-free performance metrics on a list of closed trades."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable, Sequence


def profit_factor(pnl: Iterable[float]) -> float:
    pnl = list(pnl)
    gross_win = sum(p for p in pnl if p > 0)
    gross_loss = -sum(p for p in pnl if p < 0)
    if gross_loss == 0:
        return float("inf") if gross_win > 0 else 0.0
    return gross_win / gross_loss


def max_drawdown(balances: Sequence[float]) -> tuple[float, float]:
    """Return (max drawdown in money, max drawdown in % of the running peak)."""
    peak = float("-inf")
    dd_abs = dd_pct = 0.0
    for b in balances:
        peak = max(peak, b)
        if peak > 0:
            dd_abs = max(dd_abs, peak - b)
            dd_pct = max(dd_pct, (peak - b) / peak * 100)
    return dd_abs, dd_pct


def yearly_returns(trades, initial_deposit: float) -> OrderedDict[int, float]:
    """Net P&L of each calendar year in % of the balance at the start of that year."""
    out: OrderedDict[int, float] = OrderedDict()
    balance = initial_deposit
    year_start = initial_deposit
    current = None
    for t in trades:
        y = t.close_time.year
        if current is None:
            current = y
        if y != current:
            out[current] = (balance - year_start) / year_start * 100 if year_start else 0.0
            year_start, current = balance, y
        balance += t.net
    if current is not None:
        out[current] = (balance - year_start) / year_start * 100 if year_start else 0.0
    return out


def summarize(trades, initial_deposit: float) -> dict:
    pnl = [t.net for t in trades]
    balances = [initial_deposit]
    for p in pnl:
        balances.append(balances[-1] + p)
    dd_abs, dd_pct = max_drawdown(balances)
    wins = [p for p in pnl if p > 0]
    net = sum(pnl)
    return {
        "trades": len(pnl),
        "net_profit": round(net, 2),
        "return_pct": round(net / initial_deposit * 100, 2) if initial_deposit else None,
        "profit_factor": round(profit_factor(pnl), 3),
        "win_rate_pct": round(len(wins) / len(pnl) * 100, 2) if pnl else 0.0,
        "avg_trade": round(net / len(pnl), 2) if pnl else 0.0,
        "max_dd": round(dd_abs, 2),
        "max_dd_pct": round(dd_pct, 2),
        "recovery_factor": round(net / dd_abs, 3) if dd_abs else None,
    }
