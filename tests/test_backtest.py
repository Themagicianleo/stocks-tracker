import numpy as np
import pandas as pd
import pytest

from risk_tracker.backtest import loss_limit_backtest, summarise_backtest
from risk_tracker.synthetic import gbm_prices


def _series(values):
    return pd.Series(values, index=pd.bdate_range("2020-01-01", periods=len(values)), dtype=float)


def test_every_entry_date_is_tested():
    p = gbm_prices(500, seed=0)
    bt = loss_limit_backtest(p, horizon=63)
    assert len(bt) == 500 - 63
    assert bt.index[0] == p.index[0] and bt.index[-1] == p.index[-64]


def test_hit_detection_exit_and_recovery():
    # drop 20% on day 2 then fully recover: rule exits at -20%, hold ends at +10%
    p = _series([100, 95, 80, 90, 110])
    bt = loss_limit_backtest(p, loss_limit_pct=-15, horizon=4, fee=0.0)
    row = bt.iloc[0]
    assert bool(row.hit_limit) and row.days_to_hit == 2
    assert row.rule_return == pytest.approx(-0.20)       # gap through the limit: worse than -15%
    assert row.hold_return == pytest.approx(0.10)
    assert row.worst_drawdown == pytest.approx(-0.20)


def test_limit_touched_exactly_counts_as_hit():
    bt = loss_limit_backtest(_series([100, 85, 100]), loss_limit_pct=-15, horizon=2, fee=0.0)
    assert bool(bt.iloc[0].hit_limit)


def test_no_hit_rule_equals_hold_and_drawdown_from_peak():
    p = _series([100, 120, 96, 100])            # peak 120 -> 96 is a 20% drawdown, but only -4% from entry
    bt = loss_limit_backtest(p, loss_limit_pct=-15, horizon=3, fee=0.0)
    row = bt.iloc[0]
    assert not row.hit_limit
    assert row.rule_return == row.hold_return == pytest.approx(0.0)
    assert row.worst_drawdown == pytest.approx(-0.20)


def test_fees_are_deducted():
    p = _series([100, 80, 80])
    bt = loss_limit_backtest(p, loss_limit_pct=-15, horizon=2, fee=1.0, position_usd=100)
    row = bt.iloc[0]
    assert row.hold_return == pytest.approx(-0.20 - 0.01)          # buy fee only
    assert row.rule_return == pytest.approx(-0.20 - 0.02)          # buy + sell fee


def test_summary_rates():
    p = _series([100, 80, 100, 100, 100, 100])
    bt = loss_limit_backtest(p, loss_limit_pct=-15, horizon=2, fee=0.0)
    s = summarise_backtest(bt)
    # entries: day0 hits (80), days 1..3 never fall 15%
    assert s["n_entries"] == 4
    assert s["hit_rate"] == pytest.approx(0.25)
    assert s["hit_then_recovered"] == pytest.approx(1.0)


def test_too_short_history_returns_empty():
    assert loss_limit_backtest(_series([100, 101]), horizon=63).empty
    assert summarise_backtest(pd.DataFrame())["n_entries"] == 0
