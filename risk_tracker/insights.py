"""'What this means for you': the numbers translated into your money and your own rules.

Every sentence comes from a fixed template filled with your numbers, so the
wording is predictable and never turns into advice. It describes what is at
stake and repeats the rules YOU wrote in the journal; it never says what to do.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .calibration import trailing_regime
from .volatility import TRADING_DAYS, daily_returns


def _sgd(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}S${abs(x):,.0f}"


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def personal_insights(res: dict, cfg: dict) -> list[tuple[str, list[str]]]:
    """Sections of plain-language sentences: [(heading, [sentence, ...]), ...]."""
    pos = res.get("positions")
    if pos is None or pos.empty or "pl_usd" not in pos:
        return []
    pos = pos[pos["error"] == ""] if "error" in pos else pos
    if pos.empty:
        return []
    fx_now = res.get("fx_now")
    have_fx = _ok(fx_now)
    fx = fx_now if have_fx else 1.0

    def money(x: float) -> str:
        return _sgd(x) if have_fx else f"{'-' if x < 0 else ''}US${abs(x):,.0f}"

    def signed(x: float) -> str:
        return ("+" if x >= 0 else "-") + money(abs(x))

    def more_less(x: float) -> str:
        return f"**{money(abs(x))} {'more' if x >= 0 else 'less'}**"
    sections: list[tuple[str, list[str]]] = []

    # Totals and weights, combining multiple buys of the same ticker
    by_t = pos.groupby("ticker").agg(shares=("shares", "sum"), value_usd=("value_usd", "sum"),
                                     cost_usd=("cost_usd", "sum"), pl_sgd=("pl_sgd", "sum"),
                                     pl_usd=("pl_usd", "sum"))
    total_value = float(by_t["value_usd"].sum()) * fx
    total_pl = float(by_t["pl_sgd"].sum()) if have_fx else float(by_t["pl_usd"].sum())
    lines = [f"Your holdings are worth **{money(total_value)}** in total, {more_less(total_pl)} than "
             f"you paid (after fees{' and currency changes' if have_fx else ''})."]
    if len(by_t) > 1:
        weights = (by_t["value_usd"] / by_t["value_usd"].sum()).sort_values(ascending=False)
        parts = []
        for t, w in weights.items():
            kind = " in a single company" if t in cfg["earnings_tickers"] else ""
            parts.append(f"{t} is **{w:.0%}** of your money{kind}")
        lines.append("; ".join(parts) + ".")
    sections.append(("Your money today", lines))

    # Today's move
    lines = []
    for t, row in by_t.iterrows():
        d = res["tickers"].get(t)
        if d is None:
            continue
        r = daily_returns(res["prices"][t]["adj_close"])
        if len(r) < 30:
            continue
        today_r = float(r.iloc[-1])
        today_amt = row.value_usd / (1 + today_r) * today_r * fx
        typical = d["vol"]["typical_move"]
        typical_amt = row.value_usd * typical * fx
        years = len(r) / TRADING_DAYS
        per_year = float((r.abs() >= abs(today_r)).sum()) / years
        if abs(today_r) < 0.0005:
            lines.append(f"{t} was roughly unchanged on {r.index[-1]:%d %b}. A normal day moves it about "
                         f"{typical:.1%} (roughly {money(typical_amt)} for you).")
            continue
        verb = "rose" if today_r > 0 else "fell"
        s = (f"{t} {verb} {abs(today_r):.1%} on {r.index[-1]:%d %b}, about **{money(abs(today_amt))}** "
             f"{'on' if today_r > 0 else 'off'} your holding. A normal day moves it about {typical:.1%} "
             f"(roughly {money(typical_amt)} for you)")
        if abs(today_r) > 2 * typical and per_year < 25:
            s += f", so this was a large day: moves this big happened about {per_year:.0f} times a year."
        else:
            s += ", so this was an ordinary day."
        lines.append(s)
    if lines:
        sections.append(("The latest move", lines))

    # Normal month, from the bands, plus the honesty check
    lines = []
    for t, row in by_t.iterrows():
        d = res["tickers"].get(t)
        if d is None:
            continue
        b, last = d["bands"], d["vol"]["last_price"]
        mid = b.index[len(b.index) // 2] if 0.8 not in b.index else 0.8
        lo_amt = row.shares * (b.loc[mid, "low"] - last) * fx
        hi_amt = row.shares * (b.loc[mid, "high"] - last) * fx
        s = (f"Over a typical month, your {t} holding has historically moved between "
             f"**{signed(lo_amt)}** and **{signed(hi_amt)}** about {mid:.0%} of the time")
        top = b.index.max()
        tail = (1 - top) / 2
        worst = row.shares * (b.loc[top, "low"] - last) * fx
        s += f"; in about 1 month in {round(1 / tail)} it lost more than **{money(abs(worst))}**."
        lines.append(s)
        cal = d.get("calibration")
        if cal is not None and not cal["summary"].empty:
            reg = trailing_regime(res["prices"][t]["adj_close"])["regime"].iloc[-1]
            summ = cal["summary"]
            g = summ[(summ["regime"] == reg) & (summ["level"] == mid)]
            if reg and len(g):
                v = g.iloc[0]
                lines.append(f"{t} is currently in a **{reg}** spell. In past {reg} spells this "
                             f"{mid:.0%} range actually held {v.hit_rate:.0%} of the time "
                             f"({'too narrow' if v.verdict == 'too narrow' else v.verdict}).")
    if lines:
        lines.append("These are history, not a forecast.")
        sections.append(("What a normal month looks like", lines))

    # Your own rules
    lines = []
    for r in pos.itertuples():
        cushion = (r.current_price - r.loss_limit_price) * r.shares * fx
        when = f"{r.ticker} (bought {r.buy_date:%d %b %Y})"
        if r.distance_to_limit_pct > 0:
            lines.append(f"{when} is **{r.distance_to_limit_pct:.0%} (about {money(cushion)}) above** the "
                         f"{r.loss_limit_pct:g}% loss limit you set (US${r.loss_limit_price:,.2f}).")
        else:
            lines.append(f"{when} is **below** the {r.loss_limit_pct:g}% loss limit you set "
                         f"(US${r.loss_limit_price:,.2f}) by about {money(abs(cushion))}.")
        if r.sell_rule:
            lines.append(f"Your sell rule for it, in your words: *\"{r.sell_rule}\"*")
        if r.wrong_if:
            lines.append(f"You said you'd be proven wrong if: *\"{r.wrong_if}\"*")
    sections.append(("Your own rules", lines))

    # Earnings
    lines = []
    for t, row in by_t.iterrows():
        e = res["tickers"].get(t, {}).get("earnings") or {}
        if e.get("available") and "days_until" in e and "avg_abs_move" in e and e["days_until"] <= 30:
            amt = row.value_usd * e["avg_abs_move"] * fx
            lines.append(f"{t} reports earnings in **{e['days_until']} days** ({e['next_date']:%d %b}). On past "
                         f"earnings days it moved about {e['avg_abs_move']:.1%} on average, roughly "
                         f"**{money(amt)}** on your holding, in either direction.")
    if lines:
        sections.append(("Coming up", lines))

    # Versus simply holding the benchmark
    bench = cfg["benchmark"]
    lines = []
    for r in pos.itertuples():
        if r.ticker == bench or not _ok(r.benchmark_return_pct):
            continue
        fee = r.fees_paid_usd
        alt_value = (r.cost_usd - fee) * (1 + r.benchmark_return_pct)
        diff = (alt_value - r.value_usd) * fx
        lines.append(f"If the money for {r.ticker} (bought {r.buy_date:%d %b %Y}) had gone into {bench} instead, "
                     f"you would have {more_less(diff)} today.")
    if lines:
        sections.append((f"Compared with just holding {bench}", lines))

    # Currency
    if have_fx and "fx_buy" in pos:
        fx_part = float((pos["value_usd"] * (pos["fx_now"] - pos["fx_buy"])).sum())
        if np.isfinite(fx_part) and abs(fx_part) >= 1:
            direction = "strengthened" if fx_part > 0 else "weakened"
            effect = "added" if fx_part > 0 else "cost you"
            sections.append(("Currency", [
                f"Since you bought, the US dollar has {direction} against the Singapore dollar. "
                f"That alone {effect} **{_sgd(abs(fx_part))}**, separate from how the shares did."]))
    return sections


def insights_markdown(sections: list[tuple[str, list[str]]]) -> str:
    if not sections:
        return ""
    out = ["\n## What this means for you\n"]
    for heading, lines in sections:
        out.append(f"\n**{heading}**\n")
        out += [f"- {line}" for line in lines]
    return "\n".join(out)


def insights_text(sections: list[tuple[str, list[str]]]) -> str:
    out = []
    for heading, lines in sections:
        out.append(f"  {heading}")
        out += ["    - " + line.replace("**", "").replace("*", "") for line in lines]
    return "\n".join(out)
