import numpy as np
import pandas as pd
import pytest

from risk_tracker.synthetic import gbm_prices
from risk_tracker.volatility import (TRADING_DAYS, annualise, daily_returns, rolling_volatility,
                                     typical_daily_move, volatility_summary)


def test_daily_returns_exact():
    p = pd.Series([100.0, 110.0, 99.0])
    r = daily_returns(p)
    assert r.tolist() == pytest.approx([0.10, -0.10])


def test_rolling_vol_recovers_known_sigma():
    p = gbm_prices(5000, daily_vol=0.015, drift=0.0, seed=3)
    r = daily_returns(p)
    v20 = rolling_volatility(r, 20)
    v60 = rolling_volatility(r, 60)
    assert v20.iloc[:19].isna().all() and not np.isnan(v20.iloc[19])
    assert v60.iloc[:59].isna().all()
    assert v60.mean() == pytest.approx(0.015, rel=0.05)
    assert annualise(0.01) == pytest.approx(0.01 * np.sqrt(TRADING_DAYS))


def test_typical_move_is_median_abs():
    r = pd.Series([0.01, -0.02, 0.03, -0.04, 0.05])
    assert typical_daily_move(r) == pytest.approx(0.03)


def test_typical_move_for_normal_returns():
    # median |N(0, s)| = 0.6745 s
    p = gbm_prices(20000, daily_vol=0.01, drift=0.0, seed=5)
    assert typical_daily_move(daily_returns(p)) == pytest.approx(0.006745, rel=0.05)


def test_constant_prices_have_zero_vol():
    p = pd.Series(np.full(100, 50.0), index=pd.bdate_range("2024-01-01", periods=100))
    s = volatility_summary(p)
    assert s["vol20_daily"] == 0 and s["typical_move"] == 0


def test_missing_prices_are_skipped():
    p = pd.Series([100.0, np.nan, 110.0, 121.0])
    r = daily_returns(p)
    assert r.tolist() == pytest.approx([0.10, 0.10])
