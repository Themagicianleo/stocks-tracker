import numpy as np
import pandas as pd
import pytest

from risk_tracker.bands import bands_from_simulations, log_returns, simulate_horizon_log_returns
from risk_tracker.calibration import (_rng, bands_as_of, summarise_calibration, trailing_regime,
                                      verdict_sentences, walk_forward)
from risk_tracker.synthetic import gbm_prices, regime_prices

BAND_COLS = ["low_50", "high_50", "low_80", "high_80", "low_95", "high_95"]


def test_no_future_data_leaks_into_bands():
    """Wreck every price after date i; the bands (and regime label) built at i must not change."""
    p = gbm_prices(900, daily_vol=0.01, seed=11)
    kw = dict(horizon=21, min_history=252, step=7, n_sims=500, seed=3)
    base = walk_forward(p, **kw)

    i = 252 + 7 * 20                       # one of the evaluation positions
    t = p.index[i]
    corrupted = p.copy()
    rng = np.random.default_rng(99)
    corrupted.iloc[i + 1:] = corrupted.iloc[i + 1:] * rng.uniform(0.2, 5.0, len(p) - i - 1)
    changed = walk_forward(corrupted, **kw)

    past = base.index <= t
    pd.testing.assert_frame_equal(base.loc[past, BAND_COLS], changed.loc[past, BAND_COLS])
    assert (base.loc[past, "regime"] == changed.loc[past, "regime"]).all()
    assert (base.loc[past, "vol20_annual"] == changed.loc[past, "vol20_annual"]).all()
    # ...while the realised outcome, which is legitimately in the future, does change
    assert base.loc[t, "actual"] != changed.loc[t, "actual"]


def test_bands_as_of_equals_bootstrap_on_truncated_history():
    p = gbm_prices(600, seed=2)
    i = 400
    got = bands_as_of(p, i, horizon=21, n_sims=800, seed=5)
    hist = p.iloc[: i + 1]
    sims = simulate_horizon_log_returns(log_returns(hist), 21, 800, _rng(5, i))
    pd.testing.assert_frame_equal(got, bands_from_simulations(sims, hist.iloc[-1]))
    # and the reference price is the price AT t, not later
    assert got.loc[0.5, "low"] < p.iloc[i] < got.loc[0.5, "high"]


def test_regime_uses_only_past_data():
    p = regime_prices(600, seed=1)
    a = trailing_regime(p)
    b = trailing_regime(p.iloc[:300])
    pd.testing.assert_frame_equal(a.iloc[:300], b)


def test_actual_is_price_horizon_days_later_and_inside_flag_correct():
    p = gbm_prices(400, seed=6)
    wf = walk_forward(p, horizon=10, min_history=100, step=50, n_sims=300)
    for t, row in wf.iterrows():
        pos = p.index.get_loc(t)
        assert row["actual"] == p.iloc[pos + 10]
        assert row["actual_date"] == p.index[pos + 10]
        assert row["inside_80"] == (row["low_80"] <= row["actual"] <= row["high_80"])
    assert wf.index[-1] <= p.index[-11]    # never evaluates a date without a realised outcome


def test_iid_data_is_roughly_calibrated():
    p = gbm_prices(4000, daily_vol=0.01, drift=0.0, seed=21)
    wf = walk_forward(p, horizon=21, min_history=252, step=5, n_sims=1000)
    s = summarise_calibration(wf, horizon=21, step=5)
    overall = s[s["regime"] == "all"].set_index("level")["hit_rate"]
    for lvl in (0.5, 0.8, 0.95):
        assert overall[lvl] == pytest.approx(lvl, abs=0.07)


def test_regime_switching_data_breaks_bands_in_volatile_periods():
    p = regime_prices(4000, calm_vol=0.005, volatile_vol=0.03, p_switch=0.01, seed=8)
    wf = walk_forward(p, horizon=21, min_history=252, step=5, n_sims=1000)
    s = summarise_calibration(wf, horizon=21, step=5).set_index(["regime", "level"])
    assert s.loc[("volatile", 0.95), "hit_rate"] < s.loc[("calm", 0.95), "hit_rate"]
    assert s.loc[("calm", 0.8), "verdict"] == "too wide"
    text = " ".join(verdict_sentences(s.reset_index(), "TEST"))
    assert "volatile" in text


def test_summary_and_verdict_on_handmade_table():
    wf = pd.DataFrame({
        "regime": ["calm"] * 50 + ["volatile"] * 50,
        "inside_80": [True] * 50 + [True] * 25 + [False] * 25,
        "above_80": [False] * 75 + [False] * 25,
    })
    s = summarise_calibration(wf, levels=(0.8,), horizon=1, step=1).set_index("regime")
    assert s.loc["calm", "hit_rate"] == 1.0 and s.loc["calm", "verdict"] == "too wide"
    assert s.loc["volatile", "hit_rate"] == 0.5 and s.loc["volatile", "verdict"] == "too narrow"
    assert s.loc["volatile", "miss_below"] == 0.5
    lines = verdict_sentences(s.reset_index(), "X")
    assert any("too narrow in volatile periods" in l for l in lines)


def test_short_history_gives_empty_result():
    assert walk_forward(gbm_prices(200), min_history=252).empty
    assert "not enough history" in verdict_sentences(pd.DataFrame(), "X")[0]
