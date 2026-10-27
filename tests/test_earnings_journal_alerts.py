import numpy as np
import pandas as pd
import pytest

from risk_tracker.alerts import big_move_alert, earnings_alert, loss_limit_alerts
from risk_tracker.earnings import earnings_summary, reaction_day
from risk_tracker.journal import JournalError, evaluate_positions, load_positions

IDX = pd.bdate_range("2024-01-01", periods=10)  # Mon 1 Jan .. Fri 12 Jan


def test_after_close_announcement_moves_next_session():
    assert reaction_day(pd.Timestamp("2024-01-04 16:30"), IDX) == pd.Timestamp("2024-01-05")
    assert reaction_day(pd.Timestamp("2024-01-04 08:00"), IDX) == pd.Timestamp("2024-01-04")
    # Friday after close -> Monday
    assert reaction_day(pd.Timestamp("2024-01-05 16:30"), IDX) == pd.Timestamp("2024-01-08")


def test_earnings_summary_avg_largest_and_days_until():
    p = pd.Series(100.0, index=IDX)
    p.loc["2024-01-03":] = 110.0      # +10% on Jan 3 (reaction to Jan 2 after-close)
    p.loc["2024-01-09":] = 104.5      # -5% on Jan 9 (reaction to Jan 8 after-close)
    dates = pd.Series(pd.to_datetime(["2024-01-02 16:30", "2024-01-08 16:30", "2024-01-18 16:30"]))
    s = earnings_summary(p, dates, today=pd.Timestamp("2024-01-12"))
    assert s["n"] == 2
    assert s["avg_abs_move"] == pytest.approx(0.075)
    assert s["largest_move"] == pytest.approx(0.10)
    assert s["largest_date"] == pd.Timestamp("2024-01-03")
    assert s["days_until"] == 6
    assert earnings_alert("AAPL", s["days_until"]).kind == "earnings"
    assert earnings_alert("AAPL", 8) is None


def test_earnings_unavailable_is_graceful():
    assert earnings_summary(pd.Series(1.0, index=IDX), None) == {"available": False}


def _px(values, start="2024-01-01"):
    idx = pd.bdate_range(start, periods=len(values))
    s = pd.Series(values, index=idx, dtype=float)
    return pd.DataFrame({"close": s, "adj_close": s})


def test_positions_pl_usd_sgd_limit_and_benchmark(tmp_path):
    f = tmp_path / "positions.csv"
    f.write_text("ticker,buy_date,buy_price,shares,reason,what_would_prove_me_wrong,sell_rule\n"
                 "aapl,2024-01-01,100,10,test,never,limit\n")
    pos = load_positions(f)
    prices = {"AAPL": _px([100, 105, 90])}
    fx = pd.Series([1.30, 1.32, 1.35], index=prices["AAPL"].index)
    bench = pd.Series([50, 51, 55.0], index=prices["AAPL"].index)
    ev = evaluate_positions(pos, prices, fx, bench, loss_limit_pct=-15, fee=0.99).iloc[0]
    assert ev.cost_usd == pytest.approx(1000.99)
    assert ev.pl_usd == pytest.approx(900 - 1000.99)
    assert ev.pl_sgd == pytest.approx(900 * 1.35 - 1000.99 * 1.30)
    assert ev.loss_limit_price == pytest.approx(85.0)
    assert ev.distance_to_limit_pct == pytest.approx(90 / 85 - 1)
    assert ev.fees_paid_usd == pytest.approx(0.99)
    assert ev.benchmark_return_pct == pytest.approx(0.10)
    assert ev.vs_benchmark_pct == pytest.approx((900 - 1000.99) / 1000.99 - 0.10)


def test_buy_date_on_weekend_uses_previous_close():
    pos = pd.DataFrame([{"ticker": "VT", "buy_date": pd.Timestamp("2024-01-06"), "buy_price": 10.0,
                         "shares": 1.0, "reason": "", "what_would_prove_me_wrong": "", "sell_rule": ""}])
    prices = {"VT": _px([10, 10, 10, 10, 10, 11, 12])}   # Sat 6 Jan -> uses Fri 5 Jan close (10)
    ev = evaluate_positions(pos, prices, None, prices["VT"]["close"], -15, 0.0).iloc[0]
    assert ev.benchmark_return_pct == pytest.approx(12 / 10 - 1)   # Fri 5 Jan close = 10
    assert np.isnan(ev.pl_sgd)                                      # no FX -> NaN, not a crash


def test_bad_journal_rows_rejected(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("ticker,buy_date,buy_price,shares\nVT,notadate,10,1\n")
    with pytest.raises(JournalError):
        load_positions(f)
    assert load_positions(tmp_path / "missing.csv").empty


def test_loss_limit_alerts():
    ev = pd.DataFrame([
        {"ticker": "A", "buy_date": pd.Timestamp("2024-01-01"), "distance_to_limit_pct": 0.02,
         "loss_limit_price": 85.0, "loss_limit_pct": -15, "sell_rule": "exit at -15%"},
        {"ticker": "B", "buy_date": pd.Timestamp("2024-01-01"), "distance_to_limit_pct": -0.01,
         "loss_limit_price": 85.0, "loss_limit_pct": -15, "sell_rule": ""},
        {"ticker": "C", "buy_date": pd.Timestamp("2024-01-01"), "distance_to_limit_pct": 0.10,
         "loss_limit_price": 85.0, "loss_limit_pct": -15, "sell_rule": ""},
    ])
    kinds = {a.ticker: a.kind for a in loss_limit_alerts(ev, 3.0)}
    assert kinds == {"A": "near_loss_limit", "B": "loss_limit"}


def test_big_move_alert_excludes_today_from_baseline():
    rng = np.random.default_rng(0)
    r = np.append(rng.normal(0, 0.01, 100), 0.05)   # 5 sd shock on the last day
    p = pd.Series(100 * np.cumprod(1 + np.insert(r, 0, 0)))
    a = big_move_alert("X", p.set_axis(pd.bdate_range("2024-01-01", periods=len(p))), 2.0)
    assert a is not None and "up" in a.message
    calm = pd.Series(100 * np.cumprod(1 + np.insert(rng.normal(0, 0.01, 100), 0, 0)))
    calm.iloc[-1] = calm.iloc[-2]                    # zero move today
    assert big_move_alert("X", calm.set_axis(pd.bdate_range("2024-01-01", periods=len(calm)))) is None
