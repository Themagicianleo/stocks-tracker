"""PNG charts (matplotlib, headless).

Two looks share the same drawing code:
- the Markdown report: wide figures with a title, on a light background;
- the web page (``compact=True``): phone-sized figures with larger text and a
  transparent background, drawn once per theme (light/dark) so they sit on the
  glass cards. The card heading carries the title, so compact charts have none.

Series colours are the Liquid Glass theme's system blue / orange / purple,
stepped per theme and checked for colour-blind separation.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .calibration import level_key  # noqa: E402
from .volatility import annualise, daily_returns, rolling_volatility  # noqa: E402

THEMES = {
    "light": {"series": ["#007aff", "#c77c02", "#8944ab"], "ink": "#000000", "ink2": "#6b6b70",
              "grid": "#d9d9de", "surface": "#fcfcfb"},
    "dark": {"series": ["#0a84ff", "#d97706", "#bf5af2"], "ink": "#ffffff", "ink2": "#a1a1a8",
             "grid": "#3a3a3e", "surface": "#1c1c1e"},
}
FONT = ["-apple-system", "SF Pro Text", "Helvetica Neue", "Inter", "DejaVu Sans"]


def _figure(compact: bool, wide=(10, 5), phone=(5.4, 3.5)):
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = FONT
    return plt.subplots(figsize=phone if compact else wide)


def _style(ax, t: dict, compact: bool, title: str = "", subtitle: str | None = None):
    bg = "none" if compact else t["surface"]
    ax.set_facecolor(bg)
    ax.figure.set_facecolor(bg)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(t["grid"])
    ax.tick_params(colors=t["ink2"], labelsize=11 if compact else 9)
    ax.grid(axis="y", color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    if not compact and title:
        ax.set_title(title, loc="left", color=t["ink"], fontsize=12, fontweight="bold", pad=18 if subtitle else 8)
        if subtitle:
            ax.text(0, 1.02, subtitle, transform=ax.transAxes, color=t["ink2"], fontsize=9)


def _legend(ax, t: dict, compact: bool, **kw):
    if compact:  # above the plot, so it never covers the data
        kw = {"loc": "lower left", "bbox_to_anchor": (0, 1.0), "ncol": kw.get("ncol", 3),
              "borderaxespad": 0.2, "handlelength": 1.4, "columnspacing": 1.0}
    return ax.legend(frameon=False, fontsize=10 if compact else 8, labelcolor=t["ink"], **kw)


def _save(fig, path: Path, compact: bool) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=150 if compact else 120, transparent=compact)
    plt.close(fig)
    return path


def price_with_bands(ticker: str, prices: pd.Series, bands: pd.DataFrame, horizon: int, path: Path,
                     demo: bool = False, theme: str = "light", compact: bool = False) -> Path:
    t = THEMES[theme]
    p = prices.dropna().iloc[-(126 if compact else 252):]
    last_date, last = p.index[-1], float(p.iloc[-1])
    future = pd.bdate_range(last_date, periods=horizon + 1)
    frac = np.linspace(0, 1, len(future))
    fig, ax = _figure(compact)
    ax.plot(p.index, p.values, color=t["series"][0], linewidth=2, label=f"{ticker} close")
    alphas = {0.95: 0.14, 0.8: 0.24, 0.5: 0.38}
    for lvl in sorted(bands.index, reverse=True):
        lo, hi = bands.loc[lvl, "low"], bands.loc[lvl, "high"]
        # widen with sqrt(time) from today's price to the 1-month band edges
        ax.fill_between(future, last * (lo / last) ** np.sqrt(frac), last * (hi / last) ** np.sqrt(frac),
                        color=t["series"][0], alpha=alphas.get(lvl, 0.15), linewidth=0,
                        label=f"{level_key(lvl)}% range")
    for y in (bands.loc[bands.index.max(), "low"], bands.loc[bands.index.max(), "high"]):
        ax.annotate(f"${y:,.0f}", (future[-1], y), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=10 if compact else 8, color=t["ink2"])
    ax.axvline(last_date, color=t["grid"], linewidth=1)
    sub = "1-month bands from bootstrapped past daily returns. Historical ranges, not predictions."
    _style(ax, t, compact, f"{ticker}: last year and 1-month historical ranges",
           ("DEMO - SYNTHETIC DATA. " if demo else "") + sub)
    ax.xaxis.set_major_locator(matplotlib.dates.MonthLocator(interval=2 if compact else 2))
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b"))
    if not compact:
        ax.set_ylabel("USD", color=t["ink2"])
    _legend(ax, t, compact, loc="upper left", ncol=2 if compact else 1)
    return _save(fig, path, compact)


def rolling_vol_chart(ticker: str, prices: pd.Series, path: Path, demo: bool = False,
                      theme: str = "light", compact: bool = False) -> Path:
    t = THEMES[theme]
    r = daily_returns(prices)
    fig, ax = _figure(compact, wide=(10, 4))
    span = 504 if compact else 756
    for i, w in enumerate((20, 60)):
        v = annualise(rolling_volatility(r, w)).iloc[-span:] * 100
        ax.plot(v.index, v.values, color=t["series"][i], linewidth=2 if w == 60 else 1.4, label=f"{w}-day")
    full = float(annualise(r.std()) * 100)
    ax.axhline(full, color=t["ink2"], linewidth=1, linestyle="--", label=f"long-run {full:.0f}%")
    _style(ax, t, compact, f"{ticker}: rolling volatility (annualised, last 3 years)",
           ("DEMO - SYNTHETIC DATA. " if demo else "") + "Describes how bumpy the ride has been, not where it goes.")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda y, _: f"{y:.0f}%"))
    if compact:
        ax.xaxis.set_major_locator(matplotlib.dates.MonthLocator(bymonth=[1, 7]))
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%b %y"))
    else:
        ax.set_ylabel("% per year", color=t["ink2"])
    _legend(ax, t, compact, loc="upper left", ncol=3 if compact else 1)
    return _save(fig, path, compact)


def _calibration_axes(ax, s: pd.DataFrame, t: dict, compact: bool, title: str):
    ax.plot([0.4, 1.0], [0.4, 1.0], color=t["ink2"], linewidth=1, linestyle="--", label="stated level")
    surface = "none" if compact else t["surface"]
    for i, regime in enumerate(("all", "calm", "volatile")):
        g = s[s["regime"] == regime]
        if g.empty:
            continue
        ax.plot(g["level"], g["hit_rate"], color=t["series"][i], linewidth=2, marker="o", markersize=8,
                markeredgecolor=t["surface"] if surface == "none" else surface, markeredgewidth=2,
                label=f"{regime} periods")
    _style(ax, t, compact, title)
    ax.set_xlim(0.4, 1.0)
    ax.set_ylim(0.3, 1.02)
    ax.set_xticks([0.5, 0.8, 0.95], ["50%", "80%", "95%"])
    ax.set_yticks([0.4, 0.6, 0.8, 1.0], ["40%", "60%", "80%", "100%"])
    ax.set_xlabel("stated range", color=t["ink2"], fontsize=11 if compact else 9)


def calibration_chart(summaries: dict[str, pd.DataFrame], path: Path, demo: bool = False,
                      theme: str = "light", compact: bool = False) -> Path:
    """Wide report: one panel per ticker. Compact (web): pass a single ticker."""
    t = THEMES[theme]
    tickers = [k for k, s in summaries.items() if not s.empty]
    if compact:
        fig, ax = _figure(True, phone=(5.4, 3.7))
        axes = [ax]
    else:
        fig, grid = plt.subplots(1, max(1, len(tickers)), figsize=(5.2 * max(1, len(tickers)), 4.6),
                                 squeeze=False, sharey=True)
        axes = list(grid[0])
    for ax, k in zip(axes, tickers):
        _calibration_axes(ax, summaries[k], t, compact, k)
    axes[0].set_ylabel("how often the price ended inside", color=t["ink2"], fontsize=11 if compact else 9)
    _legend(axes[0], t, compact, loc="upper left", ncol=2)
    if not compact:
        fig.suptitle(("DEMO - SYNTHETIC DATA. " if demo else "") +
                     "Out-of-sample band check: below the dashed line = bands too narrow",
                     x=0.01, ha="left", fontsize=10, color=t["ink2"])
    return _save(fig, path, compact)
