"""Historical price ranges from bootstrapped daily returns.

These are HISTORICAL RANGES, NOT PREDICTIONS: we resample past daily log
returns (with replacement) to see how wide a month of moves has tended to be.
Every band is centred on nothing in particular -- it simply inherits whatever
drift happened to be in the sample -- and says nothing about direction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_LEVELS = (0.5, 0.8, 0.95)
LABEL = "Historical ranges, not predictions"


def log_returns(prices: pd.Series | np.ndarray) -> np.ndarray:
    p = np.asarray(pd.Series(prices).dropna(), dtype=float)
    return np.diff(np.log(p))


def simulate_horizon_log_returns(log_rets: np.ndarray, horizon: int, n_sims: int,
                                 rng: np.random.Generator) -> np.ndarray:
    """Sum of ``horizon`` daily log returns drawn i.i.d. from ``log_rets``."""
    log_rets = np.asarray(log_rets, dtype=float)
    log_rets = log_rets[np.isfinite(log_rets)]
    if len(log_rets) < 2:
        raise ValueError("need at least 2 historical returns to bootstrap")
    idx = rng.integers(0, len(log_rets), size=(n_sims, horizon))
    return log_rets[idx].sum(axis=1)


def bands_from_simulations(sim_log: np.ndarray, last_price: float,
                           levels=DEFAULT_LEVELS) -> pd.DataFrame:
    rows = []
    for lvl in levels:
        tail = (1 - lvl) / 2
        lo, hi = np.quantile(sim_log, [tail, 1 - tail])
        rows.append({"level": lvl, "low": last_price * np.exp(lo), "high": last_price * np.exp(hi),
                     "low_pct": np.expm1(lo), "high_pct": np.expm1(hi)})
    return pd.DataFrame(rows).set_index("level")


def bootstrap_bands(prices: pd.Series, horizon: int = 21, levels=DEFAULT_LEVELS,
                    n_sims: int = 10000, seed: int | None = 42) -> pd.DataFrame:
    """Bands for the price ``horizon`` trading days after the last observation in ``prices``."""
    p = pd.Series(prices).dropna()
    rng = np.random.default_rng(seed)
    sims = simulate_horizon_log_returns(log_returns(p), horizon, n_sims, rng)
    return bands_from_simulations(sims, float(p.iloc[-1]), levels)
