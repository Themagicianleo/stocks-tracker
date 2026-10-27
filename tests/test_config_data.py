import os
import time

import pandas as pd
import pytest

from risk_tracker.config import ConfigError, load_config
from risk_tracker.data import DataStore, normalise_prices
from risk_tracker.synthetic import gbm_prices


def test_defaults_when_no_file(tmp_path):
    cfg = load_config(tmp_path / "missing.yaml")
    assert cfg["tickers"] == ["VT", "AAPL"]
    assert cfg["history_years"] == 10
    assert cfg["loss_limit_pct"] == -15.0
    assert cfg["fee_per_trade_usd"] == 0.99
    assert cfg["alert_threshold_sd"] == 2.0


def test_partial_override_keeps_nested_defaults(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("tickers: [msft]\nbands:\n  n_sims: 500\n")
    cfg = load_config(p)
    assert cfg["tickers"] == ["MSFT"]
    assert cfg["bands"]["n_sims"] == 500
    assert cfg["bands"]["horizon_days"] == 21


def test_positive_loss_limit_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("loss_limit_pct: 15\n")
    with pytest.raises(ConfigError):
        load_config(p)


def _frame(n=300):
    s = gbm_prices(n, seed=1)
    return pd.DataFrame({"close": s, "adj_close": s})


def test_cache_prevents_second_download(tmp_path):
    calls = []

    def fake(ticker, start):
        calls.append(ticker)
        return _frame()

    store = DataStore(tmp_path, price_downloader=fake)
    a = store.prices("AAPL")
    b = DataStore(tmp_path, price_downloader=fake).prices("AAPL")
    assert len(calls) == 1
    pd.testing.assert_series_equal(a["close"], b["close"], check_freq=False, check_names=False)


def test_network_error_falls_back_to_stale_cache(tmp_path):
    DataStore(tmp_path, price_downloader=lambda t, s: _frame()).prices("VT")
    cache = tmp_path / "VT_prices.csv"
    old = time.time() - 48 * 3600
    os.utime(cache, (old, old))

    def broken(ticker, start):
        raise ConnectionError("network down")

    store = DataStore(tmp_path, price_downloader=broken)
    df = store.prices("VT")
    assert df is not None and len(df) == 300
    assert any("using cached data" in w for w in store.warnings)


def test_network_error_without_cache_returns_none(tmp_path):
    def broken(ticker, start):
        raise ConnectionError("network down")

    store = DataStore(tmp_path, price_downloader=broken)
    assert store.prices("VT") is None
    assert store.warnings


def test_flaky_earnings_never_raises(tmp_path):
    def broken(ticker):
        raise KeyError("Earnings Date")

    store = DataStore(tmp_path, earnings_downloader=broken)
    assert store.earnings_dates("AAPL") is None
    assert any("earnings dates unavailable" in w for w in store.warnings)


def test_offline_uses_cache_only(tmp_path):
    def must_not_call(t, s):
        raise AssertionError("network used in offline mode")

    store = DataStore(tmp_path, offline=True, price_downloader=must_not_call)
    assert store.prices("VT") is None


def test_normalise_handles_multiindex_and_tz():
    idx = pd.date_range("2024-01-01", periods=3, tz="America/New_York")
    cols = pd.MultiIndex.from_tuples([("Close", "VT"), ("Adj Close", "VT")])
    raw = pd.DataFrame([[1.0, 0.9], [None, None], [3.0, 2.9]], index=idx, columns=cols)
    df = normalise_prices(raw)
    assert list(df.columns) == ["close", "adj_close"]
    assert df.index.tz is None
    assert len(df) == 2  # NaN row dropped
