"""PNG charts (matplotlib, headless)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .calibration import level_key  # noqa: E402
from .volatility import annualise, daily_returns, rolling_volatility  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]   # fixed categorical order
INK, INK_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def _style(ax, title: str, subtitle: str | None = None):
    ax.set_facecolor(SURFACE)
    ax.figure.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", color=INK, fontsize=12, fontweight="bold", pad=18 if subtitle else 8)
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, color=INK_2, fontsize=9)


def price_with_bands(ticker: str, prices: pd.Series, bands: pd.DataFrame, horizon: int, path: Path,
                     demo: bool = False) -> Path:
    p = prices.dropna().iloc[-252:]
    last_date, last = p.index[-1], float(p.iloc[-1])
    future = pd.bdate_range(last_date, periods=horizon + 1)
    t = np.linspace(0, 1, len(future))
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(p.index, p.values, color=SERIES[0], linewidth=2, label=f"{ticker} close")
    alphas = {0.95: 0.12, 0.8: 0.2, 0.5: 0.32}
    for lvl in sorted(bands.index, reverse=True):
        lo, hi = bands.loc[lvl, "low"], bands.loc[lvl, "high"]
        # widen with sqrt(time) from today's price to the 1-month band edges
        lo_path = last * (lo / last) ** np.sqrt(t)
        hi_path = last * (hi / last) ** np.sqrt(t)
        ax.fill_between(future, lo_path, hi_path, color=SERIES[0], alpha=alphas.get(lvl, 0.15),
                        linewidth=0, label=f"{level_key(lvl)}% historical range")
        for y in (lo, hi):
            ax.annotate(f"${y:,.2f}", (future[-1], y), xytext=(4, 0), textcoords="offset points",
                        va="center", fontsize=8, color=INK_2)
    ax.axvline(last_date, color=GRID, linewidth=1)
    sub = f"1-month bands from bootstrapped past daily returns. Historical ranges, not predictions."
    if demo:
        sub = "DEMO - SYNTHETIC DATA. " + sub
    _style(ax, f"{ticker}: last year and 1-month historical ranges", sub)
    ax.set_ylabel("USD", color=INK_2)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def rolling_vol_chart(ticker: str, prices: pd.Series, path: Path, demo: bool = False) -> Path:
    r = daily_returns(prices)
    fig, ax = plt.subplots(figsize=(10, 4))
    for i, w in enumerate((20, 60)):
        v = annualise(rolling_volatility(r, w)).iloc[-756:] * 100
        ax.plot(v.index, v.values, color=SERIES[i], linewidth=2 if w == 60 else 1.4, label=f"{w}-day")
        ax.annotate(f"{w}d {v.iloc[-1]:.0f}%", (v.index[-1], v.iloc[-1]), xytext=(4, 0),
                    textcoords="offset points", va="center", fontsize=8, color=INK_2)
    full = float(annualise(r.std()) * 100)
    ax.axhline(full, color=INK_2, linewidth=1, linestyle="--", label=f"full-history average {full:.0f}%")
    _style(ax, f"{ticker}: rolling volatility (annualised, last 3 years)",
           ("DEMO - SYNTHETIC DATA. " if demo else "") + "Describes how bumpy the ride has been, not where it goes.")
    ax.set_ylabel("% per year", color=INK_2)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def calibration_chart(summaries: dict[str, pd.DataFrame], path: Path, demo: bool = False) -> Path:
    tickers = [t for t, s in summaries.items() if not s.empty]
    fig, axes = plt.subplots(1, max(1, len(tickers)), figsize=(5.2 * max(1, len(tickers)), 4.6),
                             squeeze=False, sharey=True)
    for ax, t in zip(axes[0], tickers):
        s = summaries[t]
        ax.plot([0.4, 1.0], [0.4, 1.0], color=INK_2, linewidth=1, linestyle="--", label="perfect calibration")
        for i, regime in enumerate(("all", "calm", "volatile")):
            g = s[s["regime"] == regime]
            if g.empty:
                continue
            ax.plot(g["level"], g["hit_rate"], color=SERIES[i], linewidth=2, marker="o", markersize=7,
                    markeredgecolor=SURFACE, markeredgewidth=2, label=f"{regime} periods")
        _style(ax, t)
        ax.set_xlim(0.4, 1.0)
        ax.set_ylim(0.3, 1.02)
        ax.set_xticks([0.5, 0.8, 0.95], ["50%", "80%", "95%"])
        ax.set_yticks([0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], [f"{x:.0%}" for x in np.arange(0.4, 1.01, 0.1)])
        ax.set_xlabel("stated band level", color=INK_2)
    axes[0][0].set_ylabel("how often the price ended inside", color=INK_2)
    axes[0][0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.suptitle(("DEMO - SYNTHETIC DATA. " if demo else "") +
                 "Out-of-sample band check: below the dashed line = bands too narrow",
                 x=0.01, ha="left", fontsize=10, color=INK_2)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
