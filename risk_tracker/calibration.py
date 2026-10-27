"""Out-of-sample (walk-forward) check of the bootstrap bands.

For each evaluation date t we build the bands using ONLY prices up to and
including t, then look up the actual price ``horizon`` trading days later and
record whether it landed inside each band. If the "80%" band is honest it
should contain the later price about 80% of the time.

Periods are labelled calm/volatile using information available at t only:
the trailing 20-day volatility compared with the median of all trailing
20-day volatilities seen up to t.

The point is to measure how often the ranges miss, not to tune predictions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .bands import DEFAULT_LEVELS, bands_from_simulations, log_returns, simulate_horizon_log_returns
from .volatility import TRADING_DAYS


def level_key(level: float) -> str:
    return f"{level * 100:g}"


def _rng(seed: int, i: int) -> np.random.Generator:
    # one independent, reproducible stream per evaluation date
    return np.random.default_rng([seed, i])


def bands_as_of(prices: pd.Series, i: int, horizon: int = 21, levels=DEFAULT_LEVELS,
                n_sims: int = 2000, seed: int = 42) -> pd.DataFrame:
    """Bands as they would have looked at position ``i`` -- only ``prices.iloc[:i+1]`` is touched."""
    history = pd.Series(prices).dropna().iloc[: i + 1]
    sims = simulate_horizon_log_returns(log_returns(history), horizon, n_sims, _rng(seed, i))
    return bands_from_simulations(sims, float(history.iloc[-1]), levels)


def trailing_regime(prices: pd.Series, window: int = 20) -> pd.DataFrame:
    """Backward-looking volatility regime for every date (NaN until enough data)."""
    p = pd.Series(prices).dropna()
    r = p.pct_change()
    vol = r.rolling(window, min_periods=window).std()
    ref = vol.expanding(min_periods=window).median()
    regime = pd.Series(np.where(vol > ref, "volatile", "calm"), index=p.index)
    regime[vol.isna() | ref.isna()] = None
    return pd.DataFrame({"vol20_annual": vol * np.sqrt(TRADING_DAYS), "regime": regime})


def walk_forward(prices: pd.Series, horizon: int = 21, levels=DEFAULT_LEVELS, min_history: int = 252,
                 step: int = 5, n_sims: int = 2000, seed: int = 42) -> pd.DataFrame:
    p = pd.Series(prices).dropna()
    reg = trailing_regime(p)
    rows = []
    for i in range(min_history, len(p) - horizon, step):
        bands = bands_as_of(p, i, horizon, levels, n_sims, seed)
        actual = float(p.iloc[i + horizon])
        row = {"date": p.index[i], "price": float(p.iloc[i]), "actual": actual,
               "actual_date": p.index[i + horizon],
               "vol20_annual": reg["vol20_annual"].iloc[i], "regime": reg["regime"].iloc[i]}
        for lvl in levels:
            k = level_key(lvl)
            lo, hi = bands.loc[lvl, "low"], bands.loc[lvl, "high"]
            row[f"low_{k}"], row[f"high_{k}"] = lo, hi
            row[f"inside_{k}"] = bool(lo <= actual <= hi)
            row[f"above_{k}"] = bool(actual > hi)
        rows.append(row)
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def summarise_calibration(wf: pd.DataFrame, levels=DEFAULT_LEVELS, horizon: int = 21,
                          step: int = 5) -> pd.DataFrame:
    """Hit rate per (regime, level) with a rough tolerance that accounts for overlapping windows."""
    out = []
    if wf.empty:
        return pd.DataFrame()
    groups = [("all", wf)] + [(name, wf[wf["regime"] == name]) for name in ("calm", "volatile")]
    for name, g in groups:
        n = len(g)
        if n == 0:
            continue
        # consecutive 1-month windows overlap, so there are fewer independent observations than rows
        n_eff = max(1.0, n * min(1.0, step / horizon))
        for lvl in levels:
            k = level_key(lvl)
            hit = float(g[f"inside_{k}"].mean())
            above = float(g[f"above_{k}"].mean())
            tol = max(0.03, 2 * np.sqrt(lvl * (1 - lvl) / n_eff))
            if hit < lvl - tol:
                verdict = "too narrow"
            elif hit > lvl + tol:
                verdict = "too wide"
            else:
                verdict = "about right"
            out.append({"regime": name, "level": lvl, "n": n, "n_eff": round(n_eff), "hit_rate": hit,
                        "miss_above": above, "miss_below": 1 - hit - above, "tolerance": tol,
                        "verdict": verdict})
    return pd.DataFrame(out)


def verdict_sentences(summary: pd.DataFrame, ticker: str) -> list[str]:
    """Plain-language description of the calibration table for one ticker."""
    if summary.empty:
        return [f"{ticker}: not enough history for an out-of-sample check."]
    lines = []
    for regime in ("all", "calm", "volatile"):
        g = summary[summary["regime"] == regime]
        if g.empty:
            continue
        where = "over all periods" if regime == "all" else f"in {regime} periods"
        detail = ", ".join(f"the {level_key(r.level)}% band held {r.hit_rate:.0%}" for r in g.itertuples())
        verdicts = set(g["verdict"])
        if verdicts == {"about right"}:
            lines.append(f"{ticker}: bands were roughly honest {where} ({detail}).")
        elif "too narrow" in verdicts and "too wide" not in verdicts:
            lines.append(f"{ticker}: bands were too narrow {where} -- the price landed outside more "
                         f"often than stated ({detail}).")
        elif "too wide" in verdicts and "too narrow" not in verdicts:
            lines.append(f"{ticker}: bands were too wide {where} -- they overstated the risk "
                         f"({detail}).")
        else:
            lines.append(f"{ticker}: mixed results {where} ({detail}).")
    vol = summary[(summary["regime"] == "volatile")]
    calm = summary[(summary["regime"] == "calm")]
    if not vol.empty and not calm.empty:
        gap = float(calm["hit_rate"].mean() - vol["hit_rate"].mean())
        if gap > 0.05:
            lines.append(f"{ticker}: the bands missed noticeably more often when markets were already "
                         f"volatile (average hit rate {gap:.0%} lower than in calm periods).")
    all_rows = summary[summary["regime"] == "all"]
    if not all_rows.empty:
        below = float(all_rows["miss_below"].mean())
        above = float(all_rows["miss_above"].mean())
        if below > 1.5 * above and below > 0.02:
            lines.append(f"{ticker}: misses were mostly on the downside (price ended below the band).")
        elif above > 1.5 * below and above > 0.02:
            lines.append(f"{ticker}: misses were mostly on the upside (price ended above the band).")
    return lines
