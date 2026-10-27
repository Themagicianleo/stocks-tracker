"""Factual alerts: unusually large moves, earnings soon, price near the user's loss limit.

Alerts describe what happened. They are not instructions to trade.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .volatility import daily_returns


@dataclass
class Alert:
    ticker: str
    kind: str
    message: str


def big_move_alert(ticker: str, prices: pd.Series, threshold_sd: float = 2.0,
                   window: int = 60) -> Alert | None:
    """Latest daily return versus the std of the previous ``window`` returns (today excluded)."""
    r = daily_returns(prices)
    if len(r) < window + 1:
        return None
    last = float(r.iloc[-1])
    sd = float(r.iloc[-window - 1:-1].std())
    if sd == 0:
        return None
    z = last / sd
    if abs(z) > threshold_sd:
        return Alert(ticker, "big_move",
                     f"Last daily move {last:+.2%} on {r.index[-1]:%Y-%m-%d} is {abs(z):.1f} standard "
                     f"deviations ({'up' if z > 0 else 'down'}); threshold is {threshold_sd:g}.")
    return None


def earnings_alert(ticker: str, days_until: int | None, window: int = 7) -> Alert | None:
    if days_until is not None and 0 <= days_until <= window:
        when = "today" if days_until == 0 else f"in {days_until} day(s)"
        return Alert(ticker, "earnings", f"Earnings expected {when}. Past earnings days have moved "
                                         "more than typical days; see the earnings section.")
    return None


def loss_limit_alerts(evaluated: pd.DataFrame, warning_pct: float = 3.0) -> list[Alert]:
    out = []
    if evaluated.empty or "distance_to_limit_pct" not in evaluated:
        return out
    for row in evaluated.dropna(subset=["distance_to_limit_pct"]).itertuples():
        d = row.distance_to_limit_pct
        rule = f" Your journal's sell rule: \"{row.sell_rule}\"." if row.sell_rule else ""
        if d <= 0:
            out.append(Alert(row.ticker, "loss_limit",
                             f"Position bought {row.buy_date:%Y-%m-%d} is at/below its loss limit "
                             f"(${row.loss_limit_price:.2f}, {row.loss_limit_pct:g}%).{rule}"))
        elif d <= warning_pct / 100:
            out.append(Alert(row.ticker, "near_loss_limit",
                             f"Position bought {row.buy_date:%Y-%m-%d} is {d:.1%} above its loss limit "
                             f"(${row.loss_limit_price:.2f}).{rule}"))
    return out
