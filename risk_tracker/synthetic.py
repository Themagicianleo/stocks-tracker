"""Synthetic price generators for tests and the offline ``--demo`` mode.

The demo series switch between calm and volatile regimes, because real
markets do too and that is exactly what the calibration check is meant to
expose. None of this is real market data.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def business_days(n: int, end: date | str | None = None) -> pd.DatetimeIndex:
    end_ts = pd.Timestamp(end or pd.Timestamp.today()).normalize()
    return pd.bdate_range(end=end_ts, periods=n, name="date")


def gbm_prices(n: int, daily_vol: float = 0.01, drift: float = 0.0003, start_price: float = 100.0,
               seed: int = 0, end: date | str | None = "2024-12-31") -> pd.Series:
    """Constant-volatility geometric random walk."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, daily_vol, n - 1)
    prices = start_price * np.exp(np.concatenate([[0.0], np.cumsum(rets)]))
    return pd.Series(prices, index=business_days(n, end), name="close")


def regime_switching_returns(n: int, calm_vol: float, volatile_vol: float, p_switch: float,
                             drift: float, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Daily log returns from a two-state Markov regime model. Returns (returns, is_volatile)."""
    state = np.zeros(n, dtype=bool)
    s = False
    for i in range(n):
        # volatile spells are shorter than calm ones
        if rng.random() < (p_switch * 3 if s else p_switch):
            s = not s
        state[i] = s
    vol = np.where(state, volatile_vol, calm_vol)
    # Student-t shocks (df=4) scaled to unit variance give realistic fat tails
    shocks = rng.standard_t(4, n) / np.sqrt(2.0)
    return drift + vol * shocks, state


def regime_prices(n: int, calm_vol: float = 0.007, volatile_vol: float = 0.025, p_switch: float = 0.01,
                  drift: float = 0.0003, start_price: float = 100.0, seed: int = 0,
                  end: date | str | None = "2024-12-31") -> pd.Series:
    rng = np.random.default_rng(seed)
    rets, _ = regime_switching_returns(n - 1, calm_vol, volatile_vol, p_switch, drift, rng)
    prices = start_price * np.exp(np.concatenate([[0.0], np.cumsum(rets)]))
    return pd.Series(prices, index=business_days(n, end), name="close")


def _as_frame(close: pd.Series, div_yield: float = 0.0) -> pd.DataFrame:
    """Close plus an adjusted close that grows by a steady dividend yield."""
    t = np.arange(len(close))[::-1] / 252.0
    adj = close.to_numpy() * np.exp(-div_yield * t)
    return pd.DataFrame({"close": close.to_numpy(), "adj_close": adj}, index=close.index)


def _quarterly_earnings(index: pd.DatetimeIndex, today: pd.Timestamp) -> pd.Series:
    """Last Thursday of Jan/Apr/Jul/Oct at 16:30 (after the close), incl. the next upcoming one."""
    out = []
    for year in range(index[0].year, today.year + 2):
        for month in (1, 4, 7, 10):
            last = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
            thursday = last - pd.Timedelta(days=(last.weekday() - 3) % 7)
            out.append(thursday + pd.Timedelta(hours=16, minutes=30))
    s = pd.Series(sorted(out), name="earnings_date")
    s = s[s >= index[0]]
    upcoming = s[s > today]
    return pd.concat([s[s <= today], upcoming.head(1)]).reset_index(drop=True)


def demo_dataset(tickers: list[str], fx_ticker: str = "USDSGD=X", years: int = 10, seed: int = 7,
                 end: date | str | None = None) -> dict:
    """Synthetic prices for each ticker, earnings dates for AAPL-like names, and an FX series."""
    rng = np.random.default_rng(seed)
    n = int(252 * years) + 5
    today = pd.Timestamp(end or pd.Timestamp.today()).normalize()
    idx = business_days(n, today)
    profiles = {
        "VT": dict(calm_vol=0.006, volatile_vol=0.020, p_switch=0.008, drift=0.0003, start=60.0, div=0.02),
        "AAPL": dict(calm_vol=0.012, volatile_vol=0.032, p_switch=0.010, drift=0.0006, start=25.0, div=0.005),
    }
    prices, earnings = {}, {}
    for t in tickers:
        p = profiles.get(t, dict(calm_vol=0.010, volatile_vol=0.028, p_switch=0.01, drift=0.0003,
                                 start=50.0, div=0.01))
        rets, _ = regime_switching_returns(n - 1, p["calm_vol"], p["volatile_vol"], p["p_switch"],
                                           p["drift"], rng)
        if t == "AAPL":
            ed = _quarterly_earnings(idx, today)
            earnings[t] = ed
            for ts in ed[ed <= today]:
                reaction = idx.searchsorted(ts.normalize(), side="right")  # next trading day
                if 0 < reaction < n:
                    rets[reaction - 1] += rng.normal(0.0, 0.045)
        close = pd.Series(p["start"] * np.exp(np.concatenate([[0.0], np.cumsum(rets)])), index=idx)
        prices[t] = _as_frame(close, p["div"])
    fx_rets = rng.normal(0, 0.003, n - 1)
    fx = pd.Series(1.36 * np.exp(np.concatenate([[0.0], np.cumsum(fx_rets)])), index=idx)
    prices[fx_ticker] = _as_frame(fx)
    return {"prices": prices, "earnings": earnings}
