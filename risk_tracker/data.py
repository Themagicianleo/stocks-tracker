"""Download daily prices and earnings dates with yfinance, cached as CSV.

Every network call is wrapped: on failure we fall back to a stale cache if
one exists, otherwise return None. Problems are collected in
``DataStore.warnings`` so the report can show them instead of crashing.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd

PriceDownloader = Callable[[str, datetime], pd.DataFrame]
EarningsDownloader = Callable[[str], pd.Series]


def _safe_name(ticker: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", ticker)


def normalise_prices(raw: pd.DataFrame) -> pd.DataFrame:
    """Turn a yfinance frame into columns ``close`` and ``adj_close`` with a naive date index."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["close", "adj_close"])
    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    cols = {c.lower().replace(" ", "_"): c for c in df.columns}
    if "close" not in cols:
        raise ValueError("downloaded data has no Close column")
    out = pd.DataFrame(index=pd.to_datetime(df.index))
    out["close"] = pd.to_numeric(df[cols["close"]], errors="coerce").to_numpy()
    adj = cols.get("adj_close")
    out["adj_close"] = pd.to_numeric(df[adj], errors="coerce").to_numpy() if adj else out["close"]
    if out.index.tz is not None:
        out.index = out.index.tz_localize(None)
    out.index = out.index.normalize()
    out.index.name = "date"
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out["adj_close"] = out["adj_close"].fillna(out["close"])
    return out.dropna(subset=["close"])


def _quiet_yfinance():
    import logging

    # yfinance logs every failed request; we report failures ourselves
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def yfinance_prices(ticker: str, start: datetime) -> pd.DataFrame:
    import yfinance as yf

    _quiet_yfinance()

    raw = yf.download(ticker, start=start.strftime("%Y-%m-%d"), auto_adjust=False,
                      progress=False, threads=False)
    df = normalise_prices(raw)
    if df.empty:
        raise ConnectionError(f"no price data returned for {ticker}")
    return df


def yfinance_earnings(ticker: str) -> pd.Series:
    """Past and upcoming earnings timestamps in US/Eastern local time (naive)."""
    import yfinance as yf

    _quiet_yfinance()
    edf = yf.Ticker(ticker).get_earnings_dates(limit=60)
    if edf is None or len(edf) == 0:
        raise ConnectionError(f"no earnings dates returned for {ticker}")
    idx = pd.DatetimeIndex(edf.index)
    if idx.tz is not None:
        idx = idx.tz_convert("America/New_York").tz_localize(None)
    return pd.Series(sorted(set(idx)), name="earnings_date")


class DataStore:
    """Fetch-with-cache for prices and earnings dates."""

    def __init__(self, cache_dir: str | Path, history_years: int = 10,
                 max_age_hours: float = 12, offline: bool = False, refresh: bool = False,
                 price_downloader: PriceDownloader | None = None,
                 earnings_downloader: EarningsDownloader | None = None):
        self.cache_dir = Path(cache_dir)
        self.history_years = history_years
        self.max_age_hours = max_age_hours
        self.offline = offline
        self.refresh = refresh
        self.price_downloader = price_downloader or yfinance_prices
        self.earnings_downloader = earnings_downloader or yfinance_earnings
        self.warnings: list[str] = []
        self.network_calls = 0

    # -- helpers -----------------------------------------------------------------
    def _path(self, ticker: str, kind: str) -> Path:
        return self.cache_dir / f"{_safe_name(ticker)}_{kind}.csv"

    def _is_fresh(self, path: Path, max_age_hours: float) -> bool:
        if not path.exists():
            return False
        age_h = (time.time() - path.stat().st_mtime) / 3600
        return age_h < max_age_hours

    def _start(self) -> datetime:
        return datetime.now() - timedelta(days=int(365.25 * self.history_years) + 7)

    # -- prices ------------------------------------------------------------------
    def _read_prices(self, path: Path) -> pd.DataFrame | None:
        try:
            df = pd.read_csv(path, index_col="date", parse_dates=["date"])
            return df if not df.empty else None
        except Exception as exc:  # corrupt cache file
            self.warnings.append(f"Could not read cache {path.name}: {exc}")
            return None

    def prices(self, ticker: str) -> pd.DataFrame | None:
        path = self._path(ticker, "prices")
        cached = self._read_prices(path) if path.exists() else None
        if cached is not None and (self.offline or (not self.refresh and self._is_fresh(path, self.max_age_hours))):
            return cached
        if self.offline:
            self.warnings.append(f"{ticker}: offline mode and no cached data")
            return None
        try:
            self.network_calls += 1
            df = self.price_downloader(ticker, self._start())
            if df is None or df.empty:
                raise ConnectionError("empty response")
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            df.to_csv(path)
            return df
        except Exception as exc:
            if cached is not None:
                self.warnings.append(
                    f"{ticker}: download failed ({type(exc).__name__}); using cached data "
                    f"up to {cached.index.max():%Y-%m-%d}")
                return cached
            self.warnings.append(f"{ticker}: download failed and no cache available ({exc})")
            return None

    # -- earnings ----------------------------------------------------------------
    def earnings_dates(self, ticker: str) -> pd.Series | None:
        """Earnings timestamps, or None. yfinance's earnings endpoint is flaky, so never raise."""
        path = self._path(ticker, "earnings")
        cached = None
        if path.exists():
            try:
                cached = pd.to_datetime(pd.read_csv(path)["earnings_date"]).rename("earnings_date")
            except Exception:
                cached = None
        if cached is not None and (self.offline or (not self.refresh and self._is_fresh(path, 24))):
            return cached
        if self.offline:
            self.warnings.append(f"{ticker}: offline mode and no cached earnings dates")
            return None
        try:
            self.network_calls += 1
            dates = pd.to_datetime(pd.Series(self.earnings_downloader(ticker))).dropna()
            if dates.empty:
                raise ConnectionError("empty response")
            dates = dates.sort_values().reset_index(drop=True).rename("earnings_date")
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            dates.to_frame().to_csv(path, index=False)
            return dates
        except Exception as exc:
            if cached is not None:
                self.warnings.append(f"{ticker}: earnings dates download failed; using cached list")
                return cached
            self.warnings.append(
                f"{ticker}: earnings dates unavailable ({type(exc).__name__}). "
                "Earnings sections are skipped.")
            return None


class DemoStore:
    """Same interface as DataStore but serves clearly-labelled synthetic data. No network, no cache."""

    is_demo = True

    def __init__(self, tickers: list[str], fx_ticker: str, history_years: int = 10, seed: int = 7):
        from .synthetic import demo_dataset

        self.data = demo_dataset(tickers, fx_ticker, years=history_years, seed=seed)
        self.warnings: list[str] = [
            "DEMO MODE: all prices, earnings dates and FX rates are SYNTHETIC. "
            "Nothing in this report describes real securities."]
        self.network_calls = 0

    def prices(self, ticker: str) -> pd.DataFrame | None:
        df = self.data["prices"].get(ticker)
        if df is None:
            self.warnings.append(f"{ticker}: no demo data")
        return df

    def earnings_dates(self, ticker: str) -> pd.Series | None:
        return self.data["earnings"].get(ticker)
