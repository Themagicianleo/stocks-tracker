import pandas as pd
import pytest

from risk_tracker.bands import bootstrap_bands
from risk_tracker.insights import insights_markdown, personal_insights
from risk_tracker.journal import evaluate_positions
from risk_tracker.volatility import volatility_summary

CFG = {"benchmark": "VT", "earnings_tickers": ["AAPL"]}
BANNED = ["you should", "buy now", "sell now", "good time", "will rise", "will fall", "will recover",
          "recommend", "signal", "target price"]


def _px(values):
    idx = pd.bdate_range("2024-01-01", periods=len(values))
    s = pd.Series(values, index=idx, dtype=float)
    return pd.DataFrame({"close": s, "adj_close": s})


def _res(today_move=0.0):
    base = [100 + (i % 7) * 0.5 for i in range(300)]
    aapl = base[:-1] + [base[-2] * (1 + today_move)]
    prices = {"AAPL": _px(aapl), "VT": _px(base)}
    idx = prices["AAPL"].index
    fx = pd.Series(1.30, index=idx)
    fx.iloc[-1] = 1.35
    pos = pd.DataFrame([{"ticker": "AAPL", "buy_date": idx[0], "buy_price": 100.0, "shares": 10.0,
                         "reason": "r", "what_would_prove_me_wrong": "margins fall", "sell_rule": "exit at -15%"}])
    ev = evaluate_positions(pos, prices, fx, prices["VT"]["close"], -15, 0.99)
    tickers = {t: {"vol": volatility_summary(prices[t]["adj_close"]),
                   "bands": bootstrap_bands(prices[t]["adj_close"], n_sims=500)} for t in prices}
    tickers["AAPL"]["earnings"] = {"available": True, "days_until": 3, "next_date": idx[-1] + pd.Timedelta(days=3),
                                   "avg_abs_move": 0.04}
    return {"positions": ev, "prices": prices, "tickers": tickers, "fx_now": 1.35}, ev.iloc[0]


def _text(sections):
    return " ".join(" ".join(lines) for _, lines in sections)


def test_totals_in_sgd_and_users_own_rules_quoted():
    res, ev = _res()
    sections = dict(personal_insights(res, CFG))
    assert f"S${ev.value_usd * 1.35:,.0f}" in sections["Your money today"][0]
    rules = " ".join(sections["Your own rules"])
    assert '"exit at -15%"' in rules and '"margins fall"' in rules
    assert "earnings in **3 days**" in " ".join(sections["Coming up"])
    assert f"S${ev.value_usd * 0.04 * 1.35:,.0f}" in " ".join(sections["Coming up"])


def test_currency_effect_is_separated():
    res, ev = _res()
    cur = dict(personal_insights(res, CFG))["Currency"][0]
    assert "strengthened" in cur
    assert f"S${ev.value_usd * 0.05:,.0f}" in cur


def test_large_move_is_called_out_and_sized():
    res, ev = _res(today_move=-0.08)
    move = " ".join(dict(personal_insights(res, CFG))["The latest move"])
    assert "AAPL fell 8.0%" in move and "large day" in move


def test_no_advice_language():
    for m in (0.0, -0.08, 0.08):
        res, _ = _res(m)
        text = insights_markdown(personal_insights(res, CFG)).lower()
        for phrase in BANNED:
            assert phrase not in text


def test_no_positions_means_no_section():
    assert personal_insights({"positions": pd.DataFrame()}, CFG) == []
    assert insights_markdown([]) == ""


def test_missing_fx_falls_back_to_usd():
    res, _ = _res()
    res["fx_now"] = None
    text = _text(personal_insights(res, CFG))
    assert "US$" in text and "S$" not in text.replace("US$", "")
