from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

BG, FG, GRID = "#0d1117", "#c9d1d9", "#21262d"
UP, DOWN, ACCENT, MUTED = "#3fb950", "#f85149", "#58a6ff", "#8b949e"


def _style(ax) -> None:
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(color=GRID, linewidth=0.8)
    ax.yaxis.label.set_color(MUTED)


def _fig(rows: int = 1, heights=None, size=(11, 5.2)):
    fig, axes = plt.subplots(rows, 1, figsize=size, sharex=rows > 1,
                             gridspec_kw={"height_ratios": heights} if heights else None)
    fig.patch.set_facecolor(BG)
    return fig, axes


def plot_equity(report, path: str, title: str | None = None) -> None:
    curve = report.equity_curve()
    times, bal = [t for t, _ in curve], [b for _, b in curve]
    peak, dd = float("-inf"), []
    for b in bal:
        peak = max(peak, b)
        dd.append((b - peak) / peak * 100 if peak else 0)
    fig, (ax1, ax2) = _fig(2, [3, 1])
    for ax in (ax1, ax2):
        _style(ax)
    color = UP if bal[-1] >= bal[0] else DOWN
    ax1.plot(times, bal, color=color, linewidth=1.4)
    ax1.fill_between(times, bal, bal[0], color=color, alpha=0.08)
    ax1.axhline(bal[0], color=MUTED, linewidth=0.8, linestyle="--")
    ax1.set_ylabel("balance")
    ax2.fill_between(times, dd, 0, color=DOWN, alpha=0.5, linewidth=0)
    ax2.set_ylabel("drawdown %")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    s = report.summary()
    ax1.set_title(title or f"{report.expert} · {report.symbol} · {report.period}",
                  color=FG, loc="left", fontsize=12, fontweight="bold")
    ax1.text(0.99, 0.95, f"PF {s['profit_factor']:.2f}   trades {s['trades']}   "
             f"max DD {s['max_dd_pct']:.1f}%   net {s['net_profit']:+,.0f}",
             transform=ax1.transAxes, ha="right", va="top", color=FG, fontsize=10,
             bbox=dict(facecolor=GRID, edgecolor="none", boxstyle="round,pad=0.4"))
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=BG)
    plt.close(fig)


def plot_heatmap(result, x: str, y: str, path: str, metric: str = "Profit Factor") -> None:
    xs = sorted({p[x] for p in result.passes})
    ys = sorted({p[y] for p in result.passes})
    grid = [[float("nan")] * len(xs) for _ in ys]
    for p in result.passes:
        grid[ys.index(p[y])][xs.index(p[x])] = p.get(metric) or float("nan")
    fig, ax = _fig(size=(11, 4.8))
    _style(ax)
    ax.grid(False)
    vmax = max(abs(v - 1) for row in grid for v in row if v == v) or 0.1
    im = ax.imshow(grid, cmap="RdYlGn", vmin=1 - vmax, vmax=1 + vmax, aspect="auto", origin="lower")
    ax.set_xticks(range(len(xs)), [f"{v:g}" for v in xs])
    ax.set_yticks(range(len(ys)), [f"{v:g}" for v in ys])
    ax.set_xlabel(x, color=MUTED)
    ax.set_ylabel(y, color=MUTED)
    for i, row in enumerate(grid):
        for j, v in enumerate(row):
            if v == v:
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8,
                        color="#0d1117" if abs(v - 1) < vmax * 0.6 else "white")
    cb = fig.colorbar(im, ax=ax, pad=0.01)
    cb.ax.tick_params(colors=MUTED, labelsize=8)
    cb.set_label(metric, color=MUTED)
    ax.set_title(f"{result.title} — {metric} by {x} × {y} ({len(result.passes)} passes)",
                 color=FG, loc="left", fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=BG)
    plt.close(fig)


def plot_walk_forward(wf, path: str, title: str = "Walk-forward: stitched out-of-sample equity") -> None:
    fig, ax = _fig()
    _style(ax)
    balance = wf.initial_deposit
    for k, f in enumerate(wf.folds):
        xs, ys = [f.fold.oos_start], [balance]
        for t in f.oos_trades:
            balance += t.net
            xs.append(t.close_time)
            ys.append(balance)
        color = UP if ys[-1] >= ys[0] else DOWN
        ax.axvspan(f.fold.oos_start, f.fold.oos_end, color=ACCENT if k % 2 else MUTED, alpha=0.06)
        ax.plot(xs, ys, color=color, linewidth=1.4)
        label = ", ".join(f"{k2}={v:g}" if isinstance(v, (int, float)) else f"{k2}={v}"
                          for k2, v in f.best_params.items())
        ax.annotate(label, xy=(xs[0], ys[0]), xytext=(4, 10), textcoords="offset points",
                    color=MUTED, fontsize=8)
    ax.axhline(wf.initial_deposit, color=MUTED, linewidth=0.8, linestyle="--")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    s = wf.summary()
    ax.set_title(title, color=FG, loc="left", fontsize=12, fontweight="bold")
    eff = s.get("efficiency")
    ax.text(0.99, 0.95, f"OOS PF {s['profit_factor']:.2f}   folds {s['profitable_folds']}/{s['folds']} "
            f"profitable   WFE {eff if eff is not None else 'n/a'}",
            transform=ax.transAxes, ha="right", va="top", color=FG, fontsize=10,
            bbox=dict(facecolor=GRID, edgecolor="none", boxstyle="round,pad=0.4"))
    ax.set_ylabel("balance")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=BG)
    plt.close(fig)
