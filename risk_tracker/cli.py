"""Command-line interface.

    python -m risk_tracker report          # full daily report (default)
    python -m risk_tracker fetch           # just download/refresh the cache
    python -m risk_tracker report --demo   # offline demo on synthetic data
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import DISCLAIMER
from .config import ConfigError, load_config
from .data import DataStore, DemoStore


def _store(cfg: dict, args):
    if args.demo:
        return DemoStore(cfg["tickers"] + [cfg["benchmark"]], cfg["fx_ticker"], cfg["history_years"])
    return DataStore(cfg["paths"]["cache_dir"], cfg["history_years"], cfg["cache_max_age_hours"],
                     offline=args.offline, refresh=args.refresh)


def cmd_fetch(cfg: dict, args) -> int:
    store = _store(cfg, args)
    for t in dict.fromkeys(cfg["tickers"] + [cfg["benchmark"], cfg["fx_ticker"]]):
        df = store.prices(t)
        print(f"{t:<10} " + (f"{len(df):>5} days, {df.index.min():%Y-%m-%d} to {df.index.max():%Y-%m-%d}"
                             if df is not None else "unavailable"))
    for t in cfg["earnings_tickers"]:
        e = store.earnings_dates(t)
        print(f"{t:<10} earnings dates: " + (f"{len(e)}" if e is not None else "unavailable"))
    for w in store.warnings:
        print(f"! {w}")
    return 0


def _make_charts(res: dict, cfg: dict, charts_dir: Path) -> dict[str, Path]:
    from .charts import calibration_chart, price_with_bands, rolling_vol_chart

    charts_dir.mkdir(parents=True, exist_ok=True)
    charts: dict[str, Path] = {}
    for t, d in res["tickers"].items():
        close = res["prices"][t]["close"]
        charts[f"{t}_bands"] = price_with_bands(t, close, d["bands"], cfg["bands"]["horizon_days"],
                                                charts_dir / f"{t}_bands.png", res["demo"])
        charts[f"{t}_vol"] = rolling_vol_chart(t, res["prices"][t]["adj_close"],
                                               charts_dir / f"{t}_volatility.png", res["demo"])
    summaries = {t: d["calibration"]["summary"] for t, d in res["tickers"].items() if "calibration" in d}
    if summaries:
        charts["calibration"] = calibration_chart(summaries, charts_dir / "calibration.png", res["demo"])
    return charts


def _has_journal(cfg: dict) -> bool:
    from .journal import load_positions

    try:
        return len(load_positions(cfg["paths"]["positions"])) > 0
    except ValueError:
        return True  # unreadable journal: assume it holds private data


def _make_web_charts(res: dict, cfg: dict, out_dir: Path) -> dict[str, tuple[str, str]]:
    """Phone-sized charts, one light and one dark version each, as data URIs."""
    from .charts import calibration_chart, price_with_bands, rolling_vol_chart
    from .web import png_data_uri

    out_dir.mkdir(parents=True, exist_ok=True)
    charts: dict[str, tuple[str, str]] = {}

    def both(key: str, draw) -> None:
        charts[key] = tuple(png_data_uri(draw(theme, out_dir / f"{key}_{theme}.png")) for theme in ("light", "dark"))

    for t, d in res["tickers"].items():
        close, adj = res["prices"][t]["close"], res["prices"][t]["adj_close"]
        both(f"{t}_bands", lambda th, p: price_with_bands(t, close, d["bands"], cfg["bands"]["horizon_days"], p,
                                                            theme=th, compact=True))
        both(f"{t}_vol", lambda th, p: rolling_vol_chart(t, adj, p, theme=th, compact=True))
        if "calibration" in d and not d["calibration"]["summary"].empty:
            summ = {t: d["calibration"]["summary"]}
            both(f"{t}_calibration", lambda th, p: calibration_chart(summ, p, theme=th, compact=True))
    return charts


def _site_password(cfg: dict, args) -> tuple[str | None, str | None]:
    """(password, error message)."""
    password = os.environ.get(args.password_env) or None
    if password is None and not args.public:
        return None, (f"--site needs a password in the {args.password_env} environment variable "
                      "(or --public to publish a market-only page with no journal).")
    if password is None and _has_journal(cfg):
        return None, (f"Refusing to publish an unencrypted page: {cfg['paths']['positions']} contains your "
                      f"positions. Set {args.password_env}, or remove the journal for a market-only page.")
    if password is not None and len(password) < 12:
        return None, "Site password must be at least 12 characters: the encrypted page is public."
    return password, None


def cmd_report(cfg: dict, args) -> int:
    from .pipeline import run_analysis
    from .report import render_markdown, terminal_summary

    password = None
    if args.site:
        password, problem = _site_password(cfg, args)
        if problem:
            print(problem, file=sys.stderr)
            return 2
    store = _store(cfg, args)
    res = run_analysis(cfg, store, calibration=not args.no_calibration)
    if not res["tickers"]:
        print("No price data available for any ticker. Check your network or run with --demo.")
        for w in store.warnings:
            print(f"! {w}")
        print(f"\n{DISCLAIMER}")
        return 1
    stamp = f"{res['today']:%Y-%m-%d}" + ("-demo" if res["demo"] else "")
    reports_dir = Path(cfg["paths"]["reports_dir"])
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{stamp}.md"
    charts = {} if args.no_charts else _make_charts(res, cfg, Path(cfg["paths"]["charts_dir"]) / stamp)
    rel = {k: (Path("..", v).as_posix() if not Path(v).is_absolute() else str(v)) for k, v in charts.items()}
    report_path.write_text(render_markdown(res, cfg, rel), encoding="utf-8")
    if res["tickers"] and "calibration" in next(iter(res["tickers"].values())):
        frames = [d["calibration"]["walk_forward"].assign(ticker=t) for t, d in res["tickers"].items()]
        pd.concat(frames).to_csv(reports_dir / f"{stamp}-walk-forward.csv")
    print(terminal_summary(res, cfg, report_path))
    if args.site:
        from .web import build_site, render_views

        web_charts = {} if args.no_charts else _make_web_charts(res, cfg, Path(cfg["paths"]["charts_dir"]) / stamp / "web")
        last = max(d["vol"]["last_date"] for d in res["tickers"].values())
        now_sg = datetime.now(ZoneInfo("Asia/Singapore"))
        label = f"Updated {now_sg:%d %b, %H:%M} SGT \u00b7 prices to {last:%d %b %Y}"
        page = build_site(render_views(res, cfg, web_charts, label), args.site, password, res["demo"])
        print(f"\nWeb page written to {page} ({'encrypted' if password else 'NOT encrypted'})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="config.yaml", help="path to config.yaml")
    common.add_argument("--offline", action="store_true", help="never use the network; cache only")
    common.add_argument("--refresh", action="store_true", help="ignore cache age and re-download")
    common.add_argument("--demo", action="store_true",
                        help="use SYNTHETIC data (no network) to try the tool; results are not real")
    p = argparse.ArgumentParser(prog="stock-risk-tracker", parents=[common],
                                description="Describe risk on a few US holdings. No predictions, no signals.")
    sub = p.add_subparsers(dest="command")
    r = sub.add_parser("report", parents=[common], help="build the daily report (default)")
    r.add_argument("--no-calibration", action="store_true", help="skip the slower walk-forward check")
    r.add_argument("--no-charts", action="store_true", help="skip PNG charts")
    r.add_argument("--site", metavar="DIR", help="also build a phone-friendly web page in DIR")
    r.add_argument("--password-env", default="SITE_PASSWORD",
                   help="environment variable holding the web page password (default SITE_PASSWORD)")
    r.add_argument("--public", action="store_true",
                   help="build the web page WITHOUT a password; only allowed when there is no journal")
    sub.add_parser("fetch", parents=[common], help="download / refresh cached data only")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        args = build_parser().parse_args(["report"] + (argv if argv is not None else sys.argv[1:]))
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    return cmd_fetch(cfg, args) if args.command == "fetch" else cmd_report(cfg, args)


if __name__ == "__main__":
    raise SystemExit(main())
