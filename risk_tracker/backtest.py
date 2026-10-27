"""Test a loss-limit rule from EVERY possible historical entry date.

For each entry date we follow the next ``horizon`` trading days and record:
whether the closing price fell to the loss limit, the worst peak-to-trough
drawdown, and the result with the rule (exit at the first close at or below
the limit) versus simply holding for the whole period. Using every entry
date avoids cherry-picking a lucky or unlucky start.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view


def loss_limit_backtest(prices: pd.Series, loss_limit_pct: float = -15.0, horizon: int = 63,
                        fee: float = 0.99, position_usd: float = 1000.0) -> pd.DataFrame:
    """One row per entry date. Returns are fractions, fees already deducted."""
    p = pd.Series(prices).dropna()
    if len(p) <= horizon:
        return pd.DataFrame()
    limit = loss_limit_pct / 100.0
    windows = sliding_window_view(p.to_numpy(dtype=float), horizon + 1)
    rel = windows / windows[:, :1]                      # path relative to entry, starts at 1.0
    after = rel[:, 1:] - 1.0
    hit_mask = after <= limit
    hit = hit_mask.any(axis=1)
    first = np.where(hit, hit_mask.argmax(axis=1), -1)  # offset (0 = first day after entry)
    running_max = np.maximum.accumulate(rel, axis=1)
    worst_dd = (rel / running_max - 1.0).min(axis=1)
    hold = after[:, -1]
    exit_ret = np.where(hit, after[np.arange(len(after)), np.maximum(first, 0)], hold)
    buy_fee = fee / position_usd
    hold_net = hold - buy_fee
    rule_net = exit_ret - buy_fee - np.where(hit, fee / position_usd, 0.0)
    entry_dates = p.index[: len(rel)]
    return pd.DataFrame({
        "entry_price": windows[:, 0],
        "hit_limit": hit,
        "days_to_hit": np.where(hit, first + 1, np.nan),
        "worst_drawdown": worst_dd,
        "hold_return": hold_net,
        "rule_return": rule_net,
    }, index=entry_dates)


def summarise_backtest(per_entry: pd.DataFrame) -> dict:
    if per_entry.empty:
        return {"n_entries": 0}
    hits = per_entry[per_entry["hit_limit"]]
    diff = per_entry["rule_return"] - per_entry["hold_return"]
    by_year = per_entry.groupby(per_entry.index.year)["hit_limit"].mean()
    return {
        "n_entries": int(len(per_entry)),
        "first_entry": per_entry.index[0],
        "last_entry": per_entry.index[-1],
        "hit_rate": float(per_entry["hit_limit"].mean()),
        "n_hits": int(len(hits)),
        "median_days_to_hit": float(hits["days_to_hit"].median()) if len(hits) else float("nan"),
        "worst_drawdown": float(per_entry["worst_drawdown"].min()),
        "worst_drawdown_date": per_entry["worst_drawdown"].idxmin(),
        "median_drawdown": float(per_entry["worst_drawdown"].median()),
        "hold_median": float(per_entry["hold_return"].median()),
        "hold_p05": float(per_entry["hold_return"].quantile(0.05)),
        "hold_p95": float(per_entry["hold_return"].quantile(0.95)),
        "hold_worst": float(per_entry["hold_return"].min()),
        "rule_median": float(per_entry["rule_return"].median()),
        "rule_p05": float(per_entry["rule_return"].quantile(0.05)),
        "rule_worst": float(per_entry["rule_return"].min()),
        "mean_rule_minus_hold": float(diff.mean()),
        # when the limit was hit, how often did the price end the period above the exit?
        "hit_then_recovered": float((hits["hold_return"] > hits["rule_return"]).mean()) if len(hits) else float("nan"),
        "hit_rate_by_year": by_year,
    }
