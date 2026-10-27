"""Run every analysis and collect the results into one dict for the report."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .alerts import big_move_alert, earnings_alert, loss_limit_alerts
from .backtest import loss_limit_backtest, summarise_backtest
from .bands import bootstrap_bands
from .calibration import summarise_calibration, verdict_sentences, walk_forward
from .earnings import earnings_summary
from .insights import personal_insights
from .journal import evaluate_positions, load_positions
from .volatility import volatility_summary


def run_analysis(cfg: dict, store, calibration: bool = True, today: pd.Timestamp | None = None) -> dict:
    today = pd.Timestamp(today or pd.Timestamp.today()).normalize()
    res: dict = {"today": today, "demo": getattr(store, "is_demo", False), "tickers": {},
                 "warnings": store.warnings}
    prices: dict[str, pd.DataFrame] = {}
    wanted = list(dict.fromkeys(cfg["tickers"] + [cfg["benchmark"]]))
    for t in wanted:
        df = store.prices(t)
        if df is not None and len(df) > 70:
            prices[t] = df
        elif df is not None:
            store.warnings.append(f"{t}: only {len(df)} days of data; skipped")
    fx_df = store.prices(cfg["fx_ticker"])
    fx = fx_df["close"] if fx_df is not None and not fx_df.empty else None
    if fx is None:
        store.warnings.append("FX rate unavailable: SGD figures will be blank")

    b, bt, cal = cfg["bands"], cfg["backtest"], cfg["calibration"]
    alerts = []
    for t in cfg["tickers"]:
        if t not in prices:
            continue
        adj = prices[t]["adj_close"]
        close = prices[t]["close"]
        out: dict = {"vol": volatility_summary(adj)}
        out["vol"]["last_price"] = float(close.iloc[-1])  # show the actual quoted price
        # bands on returns from the adjusted series, anchored to today's quoted price
        bands = bootstrap_bands(adj, b["horizon_days"], b["levels"], b["n_sims"], b["seed"])
        scale = float(close.iloc[-1]) / float(adj.iloc[-1])
        bands[["low", "high"]] *= scale
        out["bands"] = bands
        per_entry = loss_limit_backtest(adj, cfg["loss_limit_pct"], bt["horizon_days"],
                                        cfg["fee_per_trade_usd"], bt["position_usd"])
        out["backtest"] = summarise_backtest(per_entry)
        if t in cfg["earnings_tickers"]:
            out["earnings"] = earnings_summary(close, store.earnings_dates(t), today)
            a = earnings_alert(t, out["earnings"].get("days_until"), cfg["earnings_alert_days"])
            if a:
                alerts.append(a)
        if calibration:
            wf = walk_forward(adj, b["horizon_days"], b["levels"], cal["min_history_days"],
                              cal["step_days"], cal["n_sims"], b["seed"])
            summ = summarise_calibration(wf, b["levels"], b["horizon_days"], cal["step_days"])
            out["calibration"] = {"walk_forward": wf, "summary": summ,
                                  "verdicts": verdict_sentences(summ, t)}
        a = big_move_alert(t, adj, cfg["alert_threshold_sd"])
        if a:
            alerts.append(a)
        res["tickers"][t] = out

    try:
        journal = Path(cfg["paths"]["positions"])
        if res["demo"] and not journal.exists() and journal.with_name("positions.example.csv").exists():
            journal = journal.with_name("positions.example.csv")
        positions = load_positions(journal)
    except ValueError as exc:
        store.warnings.append(str(exc))
        positions = pd.DataFrame()
    if res["demo"] and len(positions):
        # journal prices are real-world numbers; re-anchor them to the synthetic series
        for i, row in positions.iterrows():
            if row["ticker"] in prices:
                c = prices[row["ticker"]]["close"]
                positions.loc[i, "buy_price"] = float(c[c.index <= row["buy_date"]].iloc[-1])
        store.warnings.append("DEMO MODE: journal buy prices were replaced by the synthetic close on each buy date.")
    bench = prices.get(cfg["benchmark"])
    evaluated = evaluate_positions(positions, prices, fx,
                                   bench["close"] if bench is not None else None,
                                   cfg["loss_limit_pct"], cfg["fee_per_trade_usd"]) if len(positions) else pd.DataFrame()
    res["positions"] = evaluated
    alerts += loss_limit_alerts(evaluated, cfg["loss_limit_warning_pct"])
    res["alerts"] = alerts
    res["prices"] = prices
    res["fx_now"] = float(fx.iloc[-1]) if fx is not None else None
    res["insights"] = personal_insights(res, cfg)
    return res
