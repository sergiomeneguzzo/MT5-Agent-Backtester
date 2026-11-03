from __future__ import annotations

import math

import matplotlib.dates as mdates
from matplotlib.figure import Figure
from matplotlib.transforms import blended_transform_factory

BG, FG, GRID = "#0d1117", "#c9d1d9", "#21262d"
UP, DOWN, ACCENT, MUTED = "#3fb950", "#f85149", "#58a6ff", "#8b949e"
BADGE = {"facecolor": GRID, "edgecolor": "none", "boxstyle": "round,pad=0.4"}


def plot_equity(report, path: str, title: str | None = None) -> None:
    curve = report.equity_curve()
    times, balance = [t for t, _ in curve], [b for _, b in curve]
    drawdown, peak = [], float("-inf")
    for value in balance:
        peak = max(peak, value)
        drawdown.append((value - peak) / peak * 100 if peak else 0)

    fig, (top, bottom) = _figure(rows=2, heights=[3, 1])
    color = UP if balance[-1] >= balance[0] else DOWN
    top.plot(times, balance, color=color, linewidth=1.4)
    top.fill_between(times, balance, balance[0], color=color, alpha=0.08)
    top.axhline(balance[0], color=MUTED, linewidth=0.8, linestyle="--")
    top.set_ylabel("balance")
    bottom.fill_between(times, drawdown, 0, color=DOWN, alpha=0.5, linewidth=0)
    bottom.set_ylabel("drawdown %")
    bottom.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    s = report.summary()
    _title(top, title or f"{report.expert} · {report.symbol} · {report.period}")
    _badge(top, f"PF {s['profit_factor']:.2f}   trades {s['trades']}   "
                f"max DD {s['max_dd_pct']:.1f}%   net {s['net_profit']:+,.0f}")
    _save(fig, path)


def plot_heatmap(result, x: str, y: str, path: str, metric: str = "Profit Factor") -> None:
    xs = sorted({p[x] for p in result.passes})
    ys = sorted({p[y] for p in result.passes})
    grid = [[math.nan] * len(xs) for _ in ys]
    for p in result.passes:
        grid[ys.index(p[y])][xs.index(p[x])] = p.get(metric) or math.nan

    fig, ax = _figure(size=(11, 4.8))
    ax.grid(False)
    values = [v for row in grid for v in row if not math.isnan(v)]
    spread = max((abs(v - 1) for v in values), default=0.1) or 0.1
    image = ax.imshow(grid, cmap="RdYlGn", vmin=1 - spread, vmax=1 + spread, aspect="auto", origin="lower")
    ax.set_xticks(range(len(xs)), [f"{v:g}" for v in xs])
    ax.set_yticks(range(len(ys)), [f"{v:g}" for v in ys])
    ax.set_xlabel(x, color=MUTED)
    ax.set_ylabel(y, color=MUTED)
    for i, row in enumerate(grid):
        for j, value in enumerate(row):
            if not math.isnan(value):
                ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=8,
                        color=BG if abs(value - 1) < spread * 0.6 else "white")
    bar = fig.colorbar(image, ax=ax, pad=0.01)
    bar.ax.tick_params(colors=MUTED, labelsize=8)
    bar.set_label(metric, color=MUTED)
    _title(ax, f"{result.title} · {metric} by {x} × {y} ({len(result.passes)} passes)")
    _save(fig, path)


def plot_walk_forward(wf, path: str, title: str = "Walk-forward: stitched out-of-sample equity") -> None:
    fig, ax = _figure()
    balance = wf.initial_deposit
    for n, fold in enumerate(wf.folds):
        xs, ys = [fold.fold.oos_start], [balance]
        for trade in fold.oos_trades:
            balance += trade.net
            xs.append(trade.close_time)
            ys.append(balance)
        ax.axvspan(fold.fold.oos_start, fold.fold.oos_end, color=ACCENT if n % 2 else MUTED, alpha=0.06)
        ax.plot(xs, ys, color=UP if ys[-1] >= ys[0] else DOWN, linewidth=1.4)
        params = ", ".join(f"{k}={v:g}" if isinstance(v, (int, float)) else f"{k}={v}"
                           for k, v in fold.best_params.items())
        bottom_of_axes = blended_transform_factory(ax.transData, ax.transAxes)
        ax.text(fold.fold.oos_start, 0.03, f" {params}", transform=bottom_of_axes, color=MUTED, fontsize=8, va="bottom")
    ax.axhline(wf.initial_deposit, color=MUTED, linewidth=0.8, linestyle="--")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.set_ylabel("balance")

    s = wf.summary()
    efficiency = s["efficiency"] if s["efficiency"] is not None else "n/a"
    _title(ax, title)
    _badge(ax, f"OOS PF {s['profit_factor']:.2f}   folds {s['profitable_folds']}/{s['folds']} profitable   "
               f"WFE {efficiency}")
    _save(fig, path)


def _figure(rows: int = 1, heights: list[int] | None = None, size: tuple[float, float] = (11, 5.2)):
    fig = Figure(figsize=size, facecolor=BG)
    axes = fig.subplots(rows, 1, sharex=rows > 1, gridspec_kw={"height_ratios": heights} if heights else None)
    for ax in axes if rows > 1 else [axes]:
        ax.set_facecolor(BG)
        for spine in ax.spines.values():
            spine.set_color(GRID)
        ax.tick_params(colors=MUTED, labelsize=9)
        ax.grid(color=GRID, linewidth=0.8)
        ax.yaxis.label.set_color(MUTED)
    return fig, axes


def _title(ax, text: str) -> None:
    ax.set_title(text, color=FG, loc="left", fontsize=12, fontweight="bold")


def _badge(ax, text: str) -> None:
    ax.text(0.99, 0.95, text, transform=ax.transAxes, ha="right", va="top", color=FG, fontsize=10, bbox=BADGE)


def _save(fig: Figure, path: str) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=BG)
