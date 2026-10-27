"""The investment journal (positions.csv) and how each position is doing against its own rules.

Each row is one buy trade. Columns:
ticker, buy_date, buy_price, shares, reason, what_would_prove_me_wrong, sell_rule
An optional ``loss_limit_pct`` column overrides the config loss limit for that row.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REQUIRED = ["ticker", "buy_date", "buy_price", "shares"]
TEXT = ["reason", "what_would_prove_me_wrong", "sell_rule"]


class JournalError(ValueError):
    pass


def load_positions(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=REQUIRED + TEXT)
    df = pd.read_csv(path, dtype=str, skipinitialspace=True).dropna(how="all")
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise JournalError(f"{path}: missing column(s) {missing}")
    for c in TEXT:
        if c not in df.columns:
            df[c] = ""
    df[TEXT] = df[TEXT].fillna("")
    df["ticker"] = df["ticker"].str.upper().str.strip()
    df["buy_date"] = pd.to_datetime(df["buy_date"], errors="coerce")
    df["buy_price"] = pd.to_numeric(df["buy_price"], errors="coerce").astype(float)
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce").astype(float)
    if "loss_limit_pct" in df.columns:
        df["loss_limit_pct"] = pd.to_numeric(df["loss_limit_pct"], errors="coerce")
    bad = df[df[["buy_date", "buy_price", "shares"]].isna().any(axis=1)]
    if len(bad):
        raise JournalError(f"{path}: rows {list(bad.index + 2)} have an invalid date, price or share count")
    return df.reset_index(drop=True)


def value_on_or_before(series: pd.Series, when: pd.Timestamp) -> float:
    """Last available value at or before ``when`` (handles weekends/holidays)."""
    s = pd.Series(series).dropna()
    s = s[s.index <= when]
    return float(s.iloc[-1]) if len(s) else float("nan")


def evaluate_positions(positions: pd.DataFrame, prices: dict[str, pd.DataFrame], fx: pd.Series | None,
                       benchmark: pd.Series | None, loss_limit_pct: float, fee: float) -> pd.DataFrame:
    rows = []
    for pos in positions.itertuples(index=False):
        px = prices.get(pos.ticker)
        if px is None or px.empty:
            rows.append({"ticker": pos.ticker, "buy_date": pos.buy_date, "error": "no price data"})
            continue
        close = px["close"]
        current = float(close.iloc[-1])
        as_of = close.index[-1]
        limit_pct = getattr(pos, "loss_limit_pct", np.nan)
        limit_pct = loss_limit_pct if pd.isna(limit_pct) else float(limit_pct)
        fees_paid = fee  # one buy trade per journal row
        cost = pos.buy_price * pos.shares + fees_paid
        value = current * pos.shares
        pl = value - cost
        limit_price = pos.buy_price * (1 + limit_pct / 100)
        fx_buy = value_on_or_before(fx, pos.buy_date) if fx is not None else np.nan
        fx_now = float(fx.dropna().iloc[-1]) if fx is not None and len(fx.dropna()) else np.nan
        bench_ret = np.nan
        if benchmark is not None:
            b0 = value_on_or_before(benchmark, pos.buy_date)
            bench_ret = float(benchmark.dropna().iloc[-1]) / b0 - 1 if b0 == b0 else np.nan
        ret = pl / cost
        rows.append({
            "ticker": pos.ticker, "buy_date": pos.buy_date, "shares": pos.shares,
            "buy_price": pos.buy_price, "current_price": current, "as_of": as_of,
            "cost_usd": cost, "value_usd": value, "pl_usd": pl, "return_pct": ret,
            "fx_buy": fx_buy, "fx_now": fx_now,
            # SGD view: what you paid in SGD at the time versus what it is worth in SGD now
            "pl_sgd": value * fx_now - cost * fx_buy,
            "loss_limit_pct": limit_pct, "loss_limit_price": limit_price,
            "distance_to_limit_pct": current / limit_price - 1,
            "fees_paid_usd": fees_paid,
            "benchmark_return_pct": bench_ret,
            "vs_benchmark_pct": ret - bench_ret,
            "reason": pos.reason, "wrong_if": pos.what_would_prove_me_wrong, "sell_rule": pos.sell_rule,
            "error": "",
        })
    return pd.DataFrame(rows)
