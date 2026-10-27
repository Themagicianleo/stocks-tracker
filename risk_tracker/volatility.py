"""Descriptive volatility statistics. Nothing here forecasts."""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def daily_returns(prices: pd.Series) -> pd.Series:
    """Simple daily returns, first (NaN) value dropped. Gaps/NaN prices are skipped, not filled."""
    p = pd.Series(prices).dropna()
    return p.pct_change().dropna()


def rolling_volatility(returns: pd.Series, window: int) -> pd.Series:
    """Rolling standard deviation of daily returns (needs a full window)."""
    return returns.rolling(window, min_periods=window).std()


def annualise(daily_vol: float | pd.Series) -> float | pd.Series:
    return daily_vol * np.sqrt(TRADING_DAYS)


def typical_daily_move(returns: pd.Series) -> float:
    """Median absolute daily return: a robust 'normal day' size."""
    r = returns.dropna()
    return float(r.abs().median()) if len(r) else float("nan")


def volatility_summary(prices: pd.Series) -> dict:
    r = daily_returns(prices)
    v20 = rolling_volatility(r, 20)
    v60 = rolling_volatility(r, 60)
    last_year = pd.Series(prices).dropna().iloc[-TRADING_DAYS:]
    last = float(last_year.iloc[-1])

    def _last(s: pd.Series) -> float:
        s = s.dropna()
        return float(s.iloc[-1]) if len(s) else float("nan")

    full_v20 = v20.dropna()
    pct_rank = float((full_v20 <= _last(v20)).mean()) if len(full_v20) else float("nan")
    return {
        "last_price": last,
        "last_date": pd.Series(prices).dropna().index[-1],
        "last_return": float(r.iloc[-1]) if len(r) else float("nan"),
        "vol20_daily": _last(v20),
        "vol60_daily": _last(v60),
        "vol20_annual": _last(annualise(v20)),
        "vol60_annual": _last(annualise(v60)),
        "vol_full_annual": float(annualise(r.std())) if len(r) > 1 else float("nan"),
        "vol20_percentile": pct_rank,  # where today's 20d vol sits in its own history
        "typical_move": typical_daily_move(r),
        "high_52w": float(last_year.max()),
        "low_52w": float(last_year.min()),
        "from_52w_high": last / float(last_year.max()) - 1,
        "n_days": int(len(r)),
    }
