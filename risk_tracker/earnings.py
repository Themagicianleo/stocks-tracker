"""How much the price moved around past earnings announcements."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .volatility import daily_returns, typical_daily_move


def reaction_day(announcement: pd.Timestamp, trading_days: pd.DatetimeIndex) -> pd.Timestamp | None:
    """First session that can react to the news.

    Announcements at/after 12:00 (US companies like AAPL report after the 16:00
    close) or with no time attached are assumed to move the NEXT session;
    morning announcements move the same session.
    """
    ts = pd.Timestamp(announcement)
    day = ts.normalize()
    after_close = ts.hour >= 12 or ts == day
    pos = trading_days.searchsorted(day, side="right" if after_close else "left")
    return trading_days[pos] if pos < len(trading_days) else None


def earnings_moves(prices: pd.Series, earnings_dates: pd.Series) -> pd.DataFrame:
    """Close-to-close move on each past earnings reaction day."""
    p = pd.Series(prices).dropna()
    r = daily_returns(p)
    rows = []
    for ts in pd.to_datetime(pd.Series(earnings_dates)).dropna():
        d = reaction_day(ts, p.index)
        if d is None or d not in r.index:
            continue
        rows.append({"announced": ts, "reaction_day": d, "move": float(r.loc[d])})
    return pd.DataFrame(rows, columns=["announced", "reaction_day", "move"]).drop_duplicates("reaction_day")


def earnings_summary(prices: pd.Series, earnings_dates: pd.Series | None,
                     today: pd.Timestamp | None = None) -> dict:
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    if earnings_dates is None or len(earnings_dates) == 0:
        return {"available": False}
    dates = pd.to_datetime(pd.Series(earnings_dates)).dropna()
    moves = earnings_moves(prices, dates[dates.dt.normalize() < today])
    future = dates[dates.dt.normalize() >= today].sort_values()
    out: dict = {"available": True, "n": int(len(moves))}
    if len(moves):
        i = moves["move"].abs().idxmax()
        typical = typical_daily_move(daily_returns(prices))
        out.update({
            "avg_abs_move": float(moves["move"].abs().mean()),
            "avg_move": float(moves["move"].mean()),
            "largest_move": float(moves.loc[i, "move"]),
            "largest_date": moves.loc[i, "reaction_day"],
            "typical_day": typical,
            "ratio_to_typical": float(moves["move"].abs().mean() / typical) if typical else np.nan,
            "moves": moves,
        })
    if len(future):
        nxt = future.iloc[0]
        out["next_date"] = nxt
        out["days_until"] = int((nxt.normalize() - today).days)
    return out
