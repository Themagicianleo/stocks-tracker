"""Render analysis results as Markdown and as a short terminal summary."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from . import DISCLAIMER
from .bands import LABEL
from .calibration import level_key
from .insights import insights_markdown, insights_text


def _pct(x, signed=True, digits=1) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{x:+.{digits}%}" if signed else f"{x:.{digits}%}"


def _money(x, cur="$") -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    sign = "-" if x < 0 else ""
    return f"{sign}{cur}{abs(x):,.2f}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["\n| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render_markdown(res: dict, cfg: dict, charts: dict[str, str] | None = None) -> str:
    charts = charts or {}
    today = res["today"]
    md: list[str] = []
    title = f"# Stock risk report - {today:%Y-%m-%d}"
    md.append(title)
    if res["demo"]:
        md.append("\n> **DEMO MODE - SYNTHETIC DATA.** Every number below comes from simulated prices. "
                  "It shows how the tool works; it says nothing about real VT or AAPL.\n")
    md.append("This report describes volatility, historical ranges and how your holdings are doing "
              "against your own rules. It does not predict prices and never tells you to buy or sell.")
    md.append(insights_markdown(res.get("insights", [])))

    if res["warnings"]:
        md.append("\n**Data notes**\n")
        md += [f"- {w}" for w in res["warnings"]]

    # Alerts
    md.append("\n## Alerts\n")
    if res["alerts"]:
        md += [f"- **{a.ticker}** ({a.kind.replace('_', ' ')}): {a.message}" for a in res["alerts"]]
    else:
        md.append("No alerts today.")

    # Journal
    md.append("\n## Your positions\n")
    pos = res["positions"]
    if pos.empty:
        md.append(f"No positions found in `{cfg['paths']['positions']}`.")
    else:
        ok = pos[pos["error"] == ""] if "error" in pos else pos
        rows = []
        for r in ok.itertuples():
            rows.append([r.ticker, f"{r.buy_date:%Y-%m-%d}", f"{r.shares:g}", _money(r.buy_price),
                         _money(r.current_price), f"{_money(r.pl_usd)} ({_pct(r.return_pct)})",
                         _money(r.pl_sgd, "S$"), f"{_money(r.loss_limit_price)} ({_pct(r.distance_to_limit_pct)} away)",
                         _money(r.fees_paid_usd), _pct(r.benchmark_return_pct),
                         _pct(r.vs_benchmark_pct)])
        md.append(_table(["Ticker", "Bought", "Shares", "Buy", "Now", "P/L USD", "P/L SGD",
                          "Loss limit", "Fees paid", f"{cfg['benchmark']} same period", f"vs {cfg['benchmark']}"],
                         rows))
        if res.get("fx_now"):
            md.append(f"\nP/L SGD compares what you paid in SGD at the buy-date USDSGD rate with today's value "
                      f"at {res['fx_now']:.4f}, so it includes currency moves. P/L includes fees. "
                      f"'vs {cfg['benchmark']}' is your return minus the price return of {cfg['benchmark']} "
                      "since the same date (dividends excluded for both).")
        for r in ok.itertuples():
            md.append(f"\n**{r.ticker} bought {r.buy_date:%Y-%m-%d}**  \n"
                      f"Reason: {r.reason or '-'}  \nWhat would prove me wrong: {r.wrong_if or '-'}  \n"
                      f"My sell rule: {r.sell_rule or '-'}")
        for r in pos[pos.get("error", "") != ""].itertuples() if "error" in pos else []:
            md.append(f"\n- {r.ticker}: {r.error}")

    # Volatility
    md.append("\n## Volatility\n")
    rows = []
    for t, d in res["tickers"].items():
        v = d["vol"]
        rows.append([t, _money(v["last_price"]), _pct(v["last_return"]), _pct(v["typical_move"], False, 2),
                     f"{_pct(v['vol20_daily'], False, 2)} / {_pct(v['vol20_annual'], False)}",
                     f"{_pct(v['vol60_daily'], False, 2)} / {_pct(v['vol60_annual'], False)}",
                     _pct(v["vol_full_annual"], False), f"{v['vol20_percentile']:.0%}",
                     f"{_money(v['low_52w'])} - {_money(v['high_52w'])}", _pct(v["from_52w_high"])])
    md.append(_table(["Ticker", "Last", "Last day", "Typical day", "20d vol (daily / yr)",
                      "60d vol (daily / yr)", "Full-history vol", "20d vol percentile", "52-week range",
                      "From 52w high"], rows))
    md.append("\n'Typical day' is the median absolute daily move. The percentile shows where today's "
              "20-day volatility sits in its own history (90% = bumpier than 90% of past readings).")
    for t in res["tickers"]:
        if f"{t}_vol" in charts:
            md.append(f"\n![{t} rolling volatility]({charts[f'{t}_vol']})")

    # Earnings
    for t, d in res["tickers"].items():
        if "earnings" not in d:
            continue
        e = d["earnings"]
        md.append(f"\n## Earnings moves - {t}\n")
        if not e.get("available"):
            md.append("Earnings dates could not be downloaded (the yfinance earnings feed is unreliable). "
                      "Section skipped; everything else is unaffected.")
            continue
        if e.get("n"):
            md.append(f"- Past earnings reactions analysed: {e['n']}")
            md.append(f"- Average move on earnings days: {_pct(e['avg_abs_move'], False)} "
                      f"(about {e['ratio_to_typical']:.1f}x a typical day of {_pct(e['typical_day'], False, 2)})")
            md.append(f"- Largest earnings-day move: {_pct(e['largest_move'])} on {e['largest_date']:%Y-%m-%d}")
        if "next_date" in e:
            md.append(f"- Next expected earnings date: {e['next_date']:%Y-%m-%d} "
                      f"({e['days_until']} days away)")
        else:
            md.append("- Next earnings date: not available")

    # Bands
    md.append(f"\n## 1-month price ranges - {LABEL.lower()}\n")
    md.append(f"**{LABEL}.** Built by resampling {cfg['history_years']} years of past daily returns "
              f"({cfg['bands']['n_sims']:,} simulated {cfg['bands']['horizon_days']}-trading-day paths). "
              "They show how far prices have tended to wander in a month; they do not say which way. "
              "See the out-of-sample check below for how often such bands have missed.")
    rows = []
    for t, d in res["tickers"].items():
        b = d["bands"]
        rows.append([t, _money(d["vol"]["last_price"])] +
                    [f"{_money(b.loc[l, 'low'])} - {_money(b.loc[l, 'high'])} "
                     f"({_pct(b.loc[l, 'low_pct'], digits=0)} / {_pct(b.loc[l, 'high_pct'], digits=0)})"
                     for l in b.index])
    levels = next(iter(res["tickers"].values()))["bands"].index if res["tickers"] else []
    md.append(_table(["Ticker", "Now"] + [f"{level_key(l)}% range" for l in levels], rows))
    for t in res["tickers"]:
        if f"{t}_bands" in charts:
            md.append(f"\n![{t} price with historical ranges]({charts[f'{t}_bands']})")

    # Backtest
    bt_cfg = cfg["backtest"]
    md.append(f"\n## Loss-limit rule over every historical entry date\n")
    md.append(f"Rule tested: exit at the first daily close {cfg['loss_limit_pct']:g}% or more below the "
              f"entry price, within {bt_cfg['horizon_days']} trading days (~3 months). Compared with holding "
              f"for the full period. Fees: {_money(cfg['fee_per_trade_usd'])} per trade on a "
              f"{_money(bt_cfg['position_usd'])} position. Every trading day is used as an entry date.")
    rows = []
    for t, d in res["tickers"].items():
        s = d["backtest"]
        if not s.get("n_entries"):
            rows.append([t, "not enough data"] + [""] * 6)
            continue
        rows.append([t, f"{s['n_entries']:,} ({s['first_entry']:%Y-%m} to {s['last_entry']:%Y-%m})",
                     f"{s['hit_rate']:.1%}", f"{_pct(s['worst_drawdown'])} (entry {s['worst_drawdown_date']:%Y-%m-%d})",
                     _pct(s["median_drawdown"]),
                     f"{_pct(s['hold_median'])} / {_pct(s['hold_p05'])} / {_pct(s['hold_worst'])}",
                     f"{_pct(s['rule_median'])} / {_pct(s['rule_p05'])} / {_pct(s['rule_worst'])}",
                     _pct(s["hit_then_recovered"], False, 0) if s["n_hits"] else "-"])
    md.append(_table(["Ticker", "Entry dates", "Hit limit", "Worst drawdown in 3m", "Median drawdown",
                      "Hold: median / 5th pct / worst", "With rule: median / 5th pct / worst",
                      "Hit, then ended higher"], rows))
    md.append("\n'Hit, then ended higher' = of the entries where the limit was hit, how often the price "
              "finished the 3 months above the exit price. Exits use daily closes, so a gap down can exit "
              "well below the limit. Overlapping windows mean entries are not independent.")
    for t, d in res["tickers"].items():
        by_year = d["backtest"].get("hit_rate_by_year")
        if by_year is not None and len(by_year):
            md.append(f"\n{t} share of entry dates that hit the limit, by entry year: " +
                      ", ".join(f"{y}: {v:.0%}" for y, v in by_year.items()))

    # Calibration
    cal = {t: d["calibration"] for t, d in res["tickers"].items() if "calibration" in d}
    if cal:
        cc = cfg["calibration"]
        md.append("\n## Out-of-sample check: how often did the ranges miss?\n")
        md.append(f"Walk-forward test: on every {cc['step_days']}th trading day (after the first "
                  f"{cc['min_history_days']} days) the bands were rebuilt using **only data available up to that "
                  f"day**, then compared with the actual price {cfg['bands']['horizon_days']} trading days later. "
                  "'Calm' / 'volatile' = trailing 20-day volatility below / above its own historical median "
                  "at the time. Verdicts allow a tolerance because neighbouring 1-month windows overlap.")
        rows = []
        for t, c in cal.items():
            for r in c["summary"].itertuples():
                rows.append([t, r.regime, f"{level_key(r.level)}%", f"{r.hit_rate:.1%}", f"{r.n} (~{r.n_eff})",
                             f"{r.miss_below:.1%} / {r.miss_above:.1%}", f"+/-{r.tolerance:.1%}", r.verdict])
        md.append(_table(["Ticker", "Period", "Stated", "Actually inside", "Checks (independent)",
                          "Missed below / above", "Tolerance", "Verdict"], rows))
        md.append("\n**Verdict in plain language**\n")
        for c in cal.values():
            md += [f"- {line}" for line in c["verdicts"]]
        if "calibration" in charts:
            md.append(f"\n![Calibration chart]({charts['calibration']})")

    md.append("\n---\n")
    md.append(f"*{DISCLAIMER}*")
    return "\n".join(md) + "\n"


def terminal_summary(res: dict, cfg: dict, report_path: Path | None = None) -> str:
    lines = []
    head = f"STOCK RISK TRACKER - {res['today']:%Y-%m-%d}"
    if res["demo"]:
        head += "   [DEMO: SYNTHETIC DATA]"
    lines += [head, "=" * len(head)]
    for w in res["warnings"]:
        lines.append(f"! {w}")
    if res.get("insights"):
        lines.append("\nWHAT THIS MEANS FOR YOU")
        lines.append(insights_text(res["insights"]))
    lines.append("\nALERTS")
    lines += [f"  * {a.ticker}: {a.message}" for a in res["alerts"]] or ["  none"]
    lines.append("\nVOLATILITY                 last     day   typical  20d/yr  60d/yr")
    for t, d in res["tickers"].items():
        v = d["vol"]
        lines.append(f"  {t:<8} {v['last_price']:>16,.2f} {_pct(v['last_return']):>7} {_pct(v['typical_move'], False, 2):>8}"
                     f" {_pct(v['vol20_annual'], False, 0):>7} {_pct(v['vol60_annual'], False, 0):>7}")
    lines.append(f"\n1-MONTH RANGES ({LABEL.upper()})")
    for t, d in res["tickers"].items():
        b = d["bands"]
        lines.append(f"  {t:<8} " + "  ".join(
            f"{level_key(l)}%: {b.loc[l, 'low']:,.2f}-{b.loc[l, 'high']:,.2f}" for l in b.index))
    pos = res["positions"]
    if not pos.empty:
        lines.append("\nPOSITIONS")
        for r in pos[pos["error"] == ""].itertuples():
            lines.append(f"  {r.ticker:<6} {r.buy_date:%Y-%m-%d}  P/L {_money(r.pl_usd)} ({_pct(r.return_pct)}) "
                         f"/ {_money(r.pl_sgd, 'S$')}  limit {_pct(r.distance_to_limit_pct)} away  "
                         f"vs {cfg['benchmark']} {_pct(r.vs_benchmark_pct)}")
    lines.append("\nLOSS-LIMIT BACKTEST (all entry dates, 3 months)")
    for t, d in res["tickers"].items():
        s = d["backtest"]
        if s.get("n_entries"):
            lines.append(f"  {t:<8} hit {cfg['loss_limit_pct']:g}% in {s['hit_rate']:.1%} of {s['n_entries']:,} "
                         f"entries; worst 3m drawdown {_pct(s['worst_drawdown'])}")
    cal = [d["calibration"] for d in res["tickers"].values() if "calibration" in d]
    if cal:
        lines.append("\nOUT-OF-SAMPLE RANGE CHECK")
        for c in cal:
            lines += [f"  - {v}" for v in c["verdicts"]]
    if report_path:
        lines.append(f"\nFull report: {report_path}")
    lines.append(f"\n{DISCLAIMER}")
    return "\n".join(lines)
