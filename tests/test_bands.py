import numpy as np
import pandas as pd
import pytest

from risk_tracker.bands import bootstrap_bands, log_returns, simulate_horizon_log_returns
from risk_tracker.synthetic import gbm_prices


def test_bands_are_nested_and_contain_last_price():
    p = gbm_prices(2000, daily_vol=0.012, drift=0.0, seed=1)
    b = bootstrap_bands(p, horizon=21, n_sims=5000, seed=0)
    last = p.iloc[-1]
    assert b.loc[0.5, "low"] < last < b.loc[0.5, "high"]
    assert b.loc[0.95, "low"] < b.loc[0.8, "low"] < b.loc[0.5, "low"]
    assert b.loc[0.5, "high"] < b.loc[0.8, "high"] < b.loc[0.95, "high"]


def test_band_width_matches_theory_for_iid_returns():
    sigma, h = 0.01, 21
    p = gbm_prices(20000, daily_vol=sigma, drift=0.0, seed=2)
    b = bootstrap_bands(p, horizon=h, n_sims=20000, seed=0)
    half_width = (np.log(b.loc[0.95, "high"]) - np.log(b.loc[0.95, "low"])) / 2
    assert half_width == pytest.approx(1.96 * sigma * np.sqrt(h), rel=0.05)


def test_constant_returns_give_zero_width_band():
    p = pd.Series(100 * 1.001 ** np.arange(300))
    b = bootstrap_bands(p, horizon=10, n_sims=200, seed=0)
    assert b.loc[0.95, "low"] == pytest.approx(b.loc[0.95, "high"])
    assert b.loc[0.95, "low"] == pytest.approx(p.iloc[-1] * 1.001 ** 10)


def test_seed_makes_bands_reproducible():
    p = gbm_prices(500, seed=4)
    pd.testing.assert_frame_equal(bootstrap_bands(p, seed=9, n_sims=1000), bootstrap_bands(p, seed=9, n_sims=1000))


def test_bootstrap_only_uses_observed_returns():
    lr = np.array([-0.02, 0.01])
    sims = simulate_horizon_log_returns(lr, horizon=3, n_sims=1000, rng=np.random.default_rng(0))
    possible = {round(a, 10) for a in [-0.06, -0.03, 0.0, 0.03]}
    assert {round(x, 10) for x in sims} <= possible


def test_too_little_history_raises():
    with pytest.raises(ValueError):
        bootstrap_bands(pd.Series([100.0, 101.0]), n_sims=10)


def test_log_returns_drop_nan():
    assert len(log_returns(pd.Series([1.0, np.nan, 2.0]))) == 1
