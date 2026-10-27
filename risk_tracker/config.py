"""Load config.yaml, fill in defaults and validate."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "tickers": ["VT", "AAPL"],
    "benchmark": "VT",
    "fx_ticker": "USDSGD=X",
    "history_years": 10,
    "loss_limit_pct": -15.0,
    "fee_per_trade_usd": 0.99,
    "alert_threshold_sd": 2.0,
    "earnings_tickers": ["AAPL"],
    "earnings_alert_days": 7,
    "loss_limit_warning_pct": 3.0,
    "bands": {"horizon_days": 21, "levels": [0.5, 0.8, 0.95], "n_sims": 10000, "seed": 42},
    "backtest": {"horizon_days": 63, "position_usd": 1000.0},
    "calibration": {"min_history_days": 252, "step_days": 5, "n_sims": 2000},
    "paths": {
        "cache_dir": "data/cache",
        "positions": "positions.csv",
        "reports_dir": "reports",
        "charts_dir": "charts",
    },
    "cache_max_age_hours": 12,
}


class ConfigError(ValueError):
    pass


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def validate(cfg: dict) -> dict:
    tickers = cfg["tickers"]
    if isinstance(tickers, str):
        tickers = [tickers]
    if not tickers:
        raise ConfigError("config: 'tickers' must list at least one ticker")
    cfg["tickers"] = [str(t).upper().strip() for t in tickers]
    cfg["earnings_tickers"] = [str(t).upper().strip() for t in cfg.get("earnings_tickers") or []]
    cfg["benchmark"] = str(cfg["benchmark"]).upper().strip()

    cfg["loss_limit_pct"] = float(cfg["loss_limit_pct"])
    if not -100 < cfg["loss_limit_pct"] < 0:
        raise ConfigError("config: 'loss_limit_pct' must be negative, e.g. -15")
    cfg["fee_per_trade_usd"] = float(cfg["fee_per_trade_usd"])
    if cfg["fee_per_trade_usd"] < 0:
        raise ConfigError("config: 'fee_per_trade_usd' cannot be negative")
    cfg["alert_threshold_sd"] = float(cfg["alert_threshold_sd"])
    if cfg["alert_threshold_sd"] <= 0:
        raise ConfigError("config: 'alert_threshold_sd' must be positive")
    if int(cfg["history_years"]) < 2:
        raise ConfigError("config: 'history_years' should be at least 2")
    cfg["history_years"] = int(cfg["history_years"])

    levels = [float(x) for x in cfg["bands"]["levels"]]
    if any(not 0 < x < 1 for x in levels):
        raise ConfigError("config: band levels must be between 0 and 1, e.g. 0.8")
    cfg["bands"]["levels"] = sorted(levels)
    for section, key in [("bands", "horizon_days"), ("bands", "n_sims"),
                         ("backtest", "horizon_days"), ("calibration", "min_history_days"),
                         ("calibration", "step_days"), ("calibration", "n_sims")]:
        cfg[section][key] = int(cfg[section][key])
        if cfg[section][key] <= 0:
            raise ConfigError(f"config: '{section}.{key}' must be positive")
    return cfg


def load_config(path: str | Path | None = "config.yaml") -> dict:
    """Read the YAML file (if it exists) on top of DEFAULTS."""
    user: dict = {}
    if path is not None and Path(path).exists():
        with open(path, encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        if not isinstance(loaded, dict):
            raise ConfigError(f"{path}: expected a mapping at the top level")
        user = loaded
    return validate(_deep_merge(DEFAULTS, user))
