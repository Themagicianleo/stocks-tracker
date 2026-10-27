"""Build the phone-friendly web page: Liquid Glass cards in four tabs.

Look and feel come from the shared ``glass.css`` used by the owner's other web
apps (msfs-buddy, Light Scout): frosted cards over a soft ambient light,
floating capsule controls and a bottom tab bar, light and dark.

When a password is given, everything inside the tabs is encrypted with
AES-256-GCM using a key derived from the password (PBKDF2-SHA256). The
published file then holds only ciphertext; the browser decrypts it locally
with the Web Crypto API. Without a password the tabs are published as-is,
which the CLI only allows when there is no journal.
"""

from __future__ import annotations

import base64
import html
import json
import math
import os
import re
from pathlib import Path

import pandas as pd

from . import DISCLAIMER
from .calibration import level_key

PBKDF2_ITERATIONS = 600_000
GLASS_CSS = Path(__file__).with_name("glass.css")


# ---------------------------------------------------------------------------- crypto
def encrypt(plaintext: str, password: str, iterations: int = PBKDF2_ITERATIONS) -> dict:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(hashes.SHA256(), 32, salt, iterations).derive(password.encode())
    ct = AESGCM(key).encrypt(iv, plaintext.encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": iterations, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def decrypt(payload: dict, password: str) -> str:
    """Python mirror of the in-browser decryption (used by tests)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    d = lambda k: base64.b64decode(payload[k])  # noqa: E731
    key = PBKDF2HMAC(hashes.SHA256(), 32, d("salt"), payload["iter"]).derive(password.encode())
    return AESGCM(key).decrypt(d("iv"), d("ct"), None).decode()


def png_data_uri(path: str | Path) -> str:
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


# ---------------------------------------------------------------------------- formatting
def _bad(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def _usd(x, dp: int = 2) -> str:
    if _bad(x):
        return "n/a"
    return f"{'-' if x < 0 else ''}${abs(x):,.{dp}f}"


def _sgd(x) -> str:
    if _bad(x):
        return "n/a"
    return f"{'-' if x < 0 else ''}S${abs(x):,.0f}"


def _signed_sgd(x) -> str:
    return "n/a" if _bad(x) else ("+" if x >= 0 else "-") + _sgd(abs(x))


def _pct(x, signed: bool = True, dp: int = 1) -> str:
    if _bad(x):
        return "n/a"
    return f"{x:+.{dp}%}" if signed else f"{x:.{dp}%}"


def _tone(x, flat: float = 0.0005) -> str:
    return "" if _bad(x) or abs(x) < flat else ("ok" if x > 0 else "danger")


def _move(x) -> str:
    """Daily move for a pill: no '-0.0%' on flat days."""
    return "0.0%" if not _bad(x) and abs(x) < 0.0005 else _pct(x)


def _two(main: str, sub: str = "") -> str:
    """A value with an optional smaller second line, so figures never break mid-way."""
    return f'<span class="v">{main}</span>' + (f'<span class="sub">{sub}</span>' if sub else "")


def _inline(text: str) -> str:
    """Escape, then the two bits of Markdown the insight templates use."""
    t = html.escape(str(text))
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return re.sub(r"\*(.+?)\*", r"<em>\1</em>", t)


def _pill(text: str, tone: str = "") -> str:
    return f'<span class="pill {tone}">{html.escape(text)}</span>'


def _kv(rows: list[tuple[str, str]]) -> str:
    body = "".join(f"<tr><th>{html.escape(k)}</th><td>{v}</td></tr>" for k, v in rows)
    return f'<table class="kv">{body}</table>'


def _card(title: str, body: str, label: str = "", extra: str = "") -> str:
    head = f'<div class="card-head"><h2>{title}</h2>{f"<span class=label>{html.escape(label)}</span>" if label else ""}</div>'
    return f'<section class="card {extra}">{head}<div class="card-body">{body}</div></section>'


def _chart(charts: dict, key: str, alt: str) -> str:
    pair = charts.get(key)
    if not pair:
        return ""
    light, dark = pair
    a = html.escape(alt)
    return (f'<div class="chart"><img class="chart-light" src="{light}" alt="{a}">'
            f'<img class="chart-dark" src="{dark}" alt="{a}"></div>')


def _title(h1: str, subtitle: str) -> str:
    return f'<div class="large-title"><h1>{h1}</h1><p class="subtitle">{subtitle}</p></div>'


# ---------------------------------------------------------------------------- views
ALERT_TONE = {"loss_limit": "danger", "near_loss_limit": "warn", "big_move": "warn", "earnings": "accent"}
ALERT_LABEL = {"loss_limit": "Below loss limit", "near_loss_limit": "Near loss limit", "big_move": "Big move",
               "earnings": "Earnings soon"}


def _hero(res: dict, cfg: dict) -> str:
    pos = res["positions"]
    pos = pos[pos["error"] == ""] if not pos.empty and "error" in pos else pos
    fx = res.get("fx_now")
    if not pos.empty and not _bad(fx):
        value = float(pos["value_usd"].sum()) * fx
        pl = float(pos["pl_sgd"].sum())
        cost = float((pos["cost_usd"] * pos["fx_buy"]).sum())
        weights = pos.groupby("ticker")["value_usd"].sum()
        weights = (weights / weights.sum()).sort_values(ascending=False)
        bar = "".join(f'<span style="flex:{w:.4f}">{html.escape(t)} {w:.0%}</span>' for t, w in weights.items())
        return (f'<section class="hero-tile"><div class="label">Your holdings</div>'
                f'<div class="hero-value">{_sgd(value)}</div>'
                f'<div class="hero-sub">{_signed_sgd(pl)} ({_pct(pl / cost if cost else float("nan"))}) since you bought'
                f' · after fees and currency</div><div class="weights">{bar}</div></section>')
    rows = "".join(
        f'<div class="hero-row"><span>{html.escape(t)}</span><span>{_usd(d["vol"]["last_price"])}</span>'
        f'<span>{_move(d["vol"]["last_return"])}</span></div>' for t, d in res["tickers"].items())
    return f'<section class="hero-tile"><div class="label">Latest close</div>{rows}</section>'


def _today(res: dict, cfg: dict, stamp: str) -> str:
    out = [_title("Today", html.escape(stamp))]
    if res["demo"]:
        out.append('<div class="banner banner-warn"><strong>Demo data.</strong> Every number here comes from '
                   'simulated prices and says nothing about real securities.</div>')
    out.append(_hero(res, cfg))
    if res["alerts"]:
        rows = "".join(
            f'<li><div class="alert-top">{_pill(ALERT_LABEL.get(a.kind, a.kind), ALERT_TONE.get(a.kind, ""))}'
            f'<strong>{html.escape(a.ticker)}</strong></div><p>{_inline(a.message)}</p></li>' for a in res["alerts"])
        out.append(_card("Alerts", f'<ul class="alerts">{rows}</ul>', f"{len(res['alerts'])}"))
    else:
        out.append(_card("Alerts", '<p class="muted">Nothing unusual today.</p>'))
    if res.get("insights"):
        for heading, lines in res["insights"]:
            items = "".join(f"<li>{_inline(x)}</li>" for x in lines)
            out.append(_card(html.escape(heading), f'<ul class="points">{items}</ul>'))
    else:
        out.append(_card("What this means for you", '<p class="muted">Add your trades as the <code>POSITIONS_CSV</code> '
                         'secret (together with <code>SITE_PASSWORD</code>) to see what today\'s prices mean for '
                         'your own money, in SGD.</p>'))
    if res["warnings"]:
        items = "".join(f"<li>{html.escape(w)}</li>" for w in res["warnings"])
        out.append(f'<details class="card notes"><summary>Data notes ({len(res["warnings"])})</summary>'
                   f'<ul class="points small">{items}</ul></details>')
    return "".join(out)


def _holdings(res: dict, cfg: dict) -> str:
    out = [_title("Holdings", "Each purchase against your own rules")]
    pos = res["positions"]
    if pos.empty:
        out.append(_card("No journal yet", '<p class="muted">Your purchases, P/L in USD and SGD, distance to your '
                         'loss limit and the comparison with VT will appear here once you add a journal.</p>'))
        return "".join(out)
    bench = cfg["benchmark"]
    for r in pos.itertuples():
        if getattr(r, "error", ""):
            out.append(_card(html.escape(r.ticker), f'<p class="muted">{html.escape(r.error)}</p>'))
            continue
        dist = r.distance_to_limit_pct
        dist_tone = "danger" if dist <= 0 else "warn" if dist <= cfg["loss_limit_warning_pct"] / 100 else ""
        rows = [
            ("Bought", _two(f"{r.buy_date:%d %b %Y}", f"{r.shares:g} shares at {_usd(r.buy_price)}")),
            ("Now", _usd(r.current_price)),
            ("Profit / loss (USD)", f'<span class="{_tone(r.pl_usd)}">{_usd(r.pl_usd)}</span>'),
            ("Profit / loss (SGD)", f'<span class="{_tone(r.pl_sgd)}">{_sgd(r.pl_sgd)}</span>'),
            (f"Loss limit ({r.loss_limit_pct:g}%)", _two(_usd(r.loss_limit_price),
             _pill(f"{_pct(dist, False, 1)} above" if dist > 0 else "below limit", dist_tone))),
            ("Fees paid", _usd(r.fees_paid_usd)),
        ]
        if r.ticker != bench:
            rows.append((f"{bench} over same period", _pct(r.benchmark_return_pct)))
            rows.append((f"You vs {bench}", f'<span class="{_tone(r.vs_benchmark_pct)}">{_pct(r.vs_benchmark_pct)}</span>'))
        notes = "".join(
            f'<div class="note"><div class="label">{lab}</div><p>{html.escape(txt)}</p></div>'
            for lab, txt in (("Why I bought", r.reason), ("What would prove me wrong", r.wrong_if),
                             ("My sell rule", r.sell_rule)) if txt)
        head = f'{html.escape(r.ticker)} <span class="pill {_tone(r.return_pct)}">{_pct(r.return_pct)}</span>'
        out.append(_card(head, _kv(rows) + (f'<div class="notes-block">{notes}</div>' if notes else "")))
    return "".join(out)


def _months_label(level: float) -> str:
    return {0.5: "Half of months", 0.8: "8 in 10 months", 0.95: "19 in 20 months"}.get(
        round(level, 2), f"{level_key(level)}% of months")


def _range_bar(b: pd.DataFrame, last: float) -> str:
    lo, hi = float(b["low"].min()), float(b["high"].max())
    pos = lambda x: (x - lo) / (hi - lo) * 100 if hi > lo else 50  # noqa: E731
    spans = "".join(
        f'<span class="band b{level_key(l)}" style="left:{pos(b.loc[l, "low"]):.1f}%;'
        f'width:{pos(b.loc[l, "high"]) - pos(b.loc[l, "low"]):.1f}%"></span>' for l in sorted(b.index, reverse=True))
    return (f'<div class="rangebar">{spans}<i class="now" style="left:{pos(last):.1f}%"></i></div>'
            f'<div class="range-ends"><span>{_usd(lo, 0)}</span><span>now {_usd(last)}</span><span>{_usd(hi, 0)}</span></div>')


def _market(res: dict, cfg: dict, charts: dict) -> str:
    out = [_title("Market", "How each holding has behaved. Descriptions, not forecasts.")]
    for t, d in res["tickers"].items():
        v, b = d["vol"], d["bands"]
        head = (f'{html.escape(t)} <span class="head-price">{_usd(v["last_price"])}</span> '
                f'<span class="pill {_tone(v["last_return"])}">{_move(v["last_return"])}</span>')
        level_rows = [(_months_label(l), _two(f'{_usd(b.loc[l, "low"], 0)} – {_usd(b.loc[l, "high"], 0)}',
                                              f'{_pct(b.loc[l, "low_pct"], dp=0)} to {_pct(b.loc[l, "high_pct"], dp=0)}'))
                      for l in b.index]
        out.append(_card(head, '<div class="label">1-month historical range</div>' + _range_bar(b, v["last_price"])
                         + _kv(level_rows)
                         + '<p class="small muted">Historical ranges, not predictions: past monthly moves '
                           'resampled from the last ' + f'{cfg["history_years"]} years. See History for how often '
                           'they missed.</p>' + _chart(charts, f"{t}_bands", f"{t} price with 1-month ranges")))
        vol_rows = [
            ("Typical day", _pct(v["typical_move"], False, 2)),
            ("Volatility, last month", f'{_pct(v["vol20_annual"], False, 0)} a year'),
            ("Volatility, last 3 months", f'{_pct(v["vol60_annual"], False, 0)} a year'),
            (f"Volatility, {cfg['history_years']}-year average", f'{_pct(v["vol_full_annual"], False, 0)} a year'),
            ("Calmer than", f'{1 - v["vol20_percentile"]:.0%} of past months' if not _bad(v["vol20_percentile"]) else "n/a"),
            ("52-week range", f'{_usd(v["low_52w"], 0)} – {_usd(v["high_52w"], 0)}'),
            ("From 52-week high", _pct(v["from_52w_high"])),
        ]
        out.append(_card(f"{html.escape(t)} volatility", _kv(vol_rows)
                         + _chart(charts, f"{t}_vol", f"{t} rolling volatility")))
        e = d.get("earnings")
        if e is not None:
            if not e.get("available"):
                body = '<p class="muted">Earnings dates could not be downloaded today (the free feed is unreliable).</p>'
            else:
                rows = []
                if "next_date" in e:
                    rows.append(("Next earnings", _two(f'{e["next_date"]:%d %b %Y}',
                                 _pill(f'in {e["days_until"]} days', "accent" if e["days_until"] <= 7 else ""))))
                if e.get("n"):
                    rows += [("Average earnings-day move", _two(_pct(e["avg_abs_move"], False),
                                                                f'{e["ratio_to_typical"]:.1f}× a normal day')),
                             ("Largest", _two(_pct(e["largest_move"]), f'{e["largest_date"]:%d %b %Y}')),
                             ("Earnings days analysed", str(e["n"]))]
                body = _kv(rows)
            out.append(_card(f"{html.escape(t)} earnings", body))
    return "".join(out)


def _history(res: dict, cfg: dict, charts: dict) -> str:
    out = [_title("History", "How your loss limit and the ranges held up in the past")]
    horizon_m = round(cfg["backtest"]["horizon_days"] / 21)
    for t, d in res["tickers"].items():
        s = d["backtest"]
        if not s.get("n_entries"):
            continue
        rows = [
            ("Start dates tested", _two(f'{s["n_entries"]:,}', f'{s["first_entry"]:%Y}–{s["last_entry"]:%Y}')),
            (f"Fell {abs(cfg['loss_limit_pct']):g}% within {horizon_m} months",
             _pill(f'{s["hit_rate"]:.0%} of the time', "warn" if s["hit_rate"] >= 0.1 else "")),
            (f"Worst drop within {horizon_m} months", _pct(s["worst_drawdown"], dp=0)),
            ("Typical worst drop", _pct(s["median_drawdown"], dp=0)),
        ]
        if s["n_hits"]:
            rows.append(("Ended higher after hitting the limit", f'{s["hit_then_recovered"]:.0%} of the time'))
        outcome = ('<div class="label">Result after 3 months</div><table class="grid"><tr><th></th><th>Typical</th>'
                   '<th>Bad<span>1 in 20</span></th><th>Worst</th></tr>'
                   + "".join(f'<tr><th>{name}</th>' + "".join(
                       f'<td class="{_tone(s[f"{key}_{q}"], 0.005)}">{_pct(s[f"{key}_{q}"], dp=0)}</td>'
                       for q in ("median", "p05", "worst")) + "</tr>"
                       for name, key in (("Just holding", "hold"), ("With your limit", "rule")))
                   + "</table>")
        by_year = s.get("hit_rate_by_year")
        bars = ""
        if by_year is not None and len(by_year):
            bars = '<div class="label">Share of start dates that hit the limit, by year</div><div class="years">' + "".join(
                f'<span class="y">{y}</span><span class="track"><span style="width:{v * 100:.1f}%">'
                f'</span></span><span class="v">{v:.0%}</span>' for y, v in by_year.items()) + "</div>"
        out.append(_card(f"{html.escape(t)}: your loss limit, tested", _kv(rows) + outcome + bars
                         + '<p class="small muted">"Bad" means 1 start date in 20 did worse. Uses daily closes, '
                           'so a gap down can exit below the limit.</p>'))
        cal = d.get("calibration")
        if cal is None or cal["summary"].empty:
            continue
        summ = cal["summary"]
        cls = {"too narrow": "narrow", "too wide": "wide", "about right": ""}
        head = "<tr><th>Stated</th><th>All</th><th>Calm</th><th>Volatile</th></tr>"
        body = ""
        for lvl in sorted(summ["level"].unique()):
            cells = ""
            for regime in ("all", "calm", "volatile"):
                g = summ[(summ["level"] == lvl) & (summ["regime"] == regime)]
                cells += (f'<td class="{cls.get(g.iloc[0].verdict, "")}">{g.iloc[0].hit_rate:.0%}</td>'
                          if len(g) else "<td>–</td>")
            body += f"<tr><th>{level_key(lvl)}%</th>{cells}</tr>"
        verdicts = "".join(f"<li>{v}</li>" for v in _short_verdicts(summ, cal["verdicts"]))
        out.append(_card(f"{html.escape(t)}: did the ranges hold?",
                         '<p class="small muted">Each range was rebuilt from data available at the time, then checked '
                         'against the price a month later. An honest 80% range holds about 80% of the time.</p>'
                         f'<table class="calib">{head}{body}</table>'
                         '<div class="calib-key small"><span><i class="key narrow"></i>missed more than stated</span>'
                         '<span><i class="key wide"></i>wider than needed</span></div>'
                         f'<ul class="points">{verdicts}</ul>'
                         + _chart(charts, f"{t}_calibration", f"{t} calibration")))
    return "".join(out)


def _short_verdicts(summ: pd.DataFrame, sentences: list[str]) -> list[str]:
    """One line per period type, plus the extra observations from the full verdict text."""
    words = {"about right": "about right", "too narrow": "too narrow: the price ended outside more often than stated",
             "too wide": "wider than needed"}
    out = []
    for regime, name in (("all", "Overall"), ("calm", "Calm periods"), ("volatile", "Volatile periods")):
        v = set(summ.loc[summ["regime"] == regime, "verdict"])
        if not v:
            continue
        text = words[next(iter(v))] if len(v) == 1 else "mixed"
        tone = "warn" if "too narrow" in v else ""
        out.append(f'<strong>{name}:</strong> <span class="{tone}">{html.escape(text)}</span>')
    for line in sentences:
        body = line.split(": ", 1)[-1]
        if not body.startswith(("bands were", "mixed results")):
            out.append(html.escape(body[:1].upper() + body[1:]))
    return out


def render_views(res: dict, cfg: dict, charts: dict, stamp: str) -> str:
    """The four tab views. This is the part that gets encrypted."""
    views = [("today", _today(res, cfg, stamp)), ("holdings", _holdings(res, cfg)),
             ("market", _market(res, cfg, charts)), ("history", _history(res, cfg, charts))]
    return "".join(f'<div class="view" data-view="{k}" role="tabpanel" hidden>{v}</div>' for k, v in views)


# ---------------------------------------------------------------------------- page
ICONS = {
    "today": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></svg>',
    "holdings": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="7" width="18" height="13" rx="3"/><path d="M8.5 7V5.5A1.5 1.5 0 0 1 10 4h4a1.5 1.5 0 0 1 1.5 1.5V7M3 12.5h18"/></svg>',
    "market": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l5-5 4 3 7-8"/><path d="M15 7h4v4"/><path d="M3 21h18"/></svg>',
    "history": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 12a8.5 8.5 0 1 0 2.5-6"/><path d="M3 4v4h4"/><path d="M12 7.5V12l3 2"/></svg>',
}
BRAND = ('<svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect width="24" height="24" '
         'rx="7" fill="var(--blue)"/><path d="M5 15.5l4-4 3 2.5 6-6.5" stroke="#fff" stroke-width="2.2" '
         'stroke-linecap="round" stroke-linejoin="round"/></svg>')

APP_CSS = """
:root { --wrap: 720px; }
.appbar .demo { color: var(--orange); font-size: 13px; font-weight: 600; }
.large-title .subtitle { margin: 4px 0 0; }
.view { display: flex; flex-direction: column; gap: 16px; }
.card h2 { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.head-price { font-weight: 500; color: var(--muted); }
.pill.ok { color: var(--green); } .pill.danger { color: var(--red); } .pill.warn { color: var(--orange); }
.pill.accent { color: var(--blue); } .pill:not(.ok):not(.danger):not(.warn):not(.accent) { color: var(--muted); }
p { margin: 0; }
.card-body > p.small { line-height: 1.4; }
.points { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 10px; line-height: 1.45; }
.points strong { font-weight: 600; }
.points em { color: var(--muted); }
.points .warn { color: var(--orange); font-weight: 600; }
.alerts { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
.alerts li + li { border-top: .5px solid var(--line); padding-top: 12px; }
.alert-top { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.alerts p { color: var(--muted); font-size: 15px; line-height: 1.4; }
.kv td { line-height: 1.3; white-space: nowrap; }
.kv th { line-height: 1.3; }
.kv td .v { display: block; }
.kv td .sub { display: block; margin-top: 3px; font-size: 13px; font-weight: 400; color: var(--muted); }
.kv td .sub .pill { font-size: 12px; padding: 2px 8px; }
.grid { width: 100%; border-collapse: collapse; font-size: 15px; }
.grid th, .grid td { padding: 9px 4px; border-top: .5px solid var(--line); text-align: right; }
.grid tr:first-child th { border-top: 0; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .02em; color: var(--muted); vertical-align: bottom; }
.grid tr:first-child th span { display: block; text-transform: none; font-weight: 400; letter-spacing: 0; }
.grid th:first-child { text-align: left; font-weight: 400; color: var(--muted); padding-left: 0; }
.grid td { font-weight: 600; }
.grid td.ok { color: var(--green); } .grid td.danger { color: var(--red); }
.card-body .label + .grid, .card-body .label + .years, .card-body .label + .rangebar { margin-top: -6px; }
.kv th { padding-right: 12px; }
.kv td .muted { font-weight: 400; }
.notes-block { display: flex; flex-direction: column; gap: 10px; padding-top: 4px; }
.note p { margin-top: 2px; line-height: 1.4; }
.notes summary { padding: 16px 18px; font-weight: 600; cursor: pointer; }
.notes ul { padding: 0 18px 16px 38px; color: var(--muted); }
.hero-tile { display: flex; flex-direction: column; gap: 6px; }
.hero-value { font-family: var(--font-display); font-size: 40px; font-weight: 700; letter-spacing: -.02em; line-height: 1.1; }
.hero-sub { color: rgba(255,255,255,.88); font-size: 15px; }
.hero-row { display: grid; grid-template-columns: 1fr auto 72px; gap: 8px; font-size: 20px; font-weight: 600; }
.hero-row span:last-child { text-align: right; font-weight: 500; color: rgba(255,255,255,.88); }
.weights { position: relative; z-index: 1; display: flex; gap: 3px; margin-top: 10px; font-size: 12px; font-weight: 600; }
.weights span { min-width: 0; overflow: hidden; white-space: nowrap; padding: 5px 8px; border-radius: 999px; background: rgba(255,255,255,.22); }
.rangebar { position: relative; height: 22px; margin: 6px 0 2px; }
.rangebar .band { position: absolute; top: 4px; bottom: 4px; border-radius: 999px; background: var(--blue); }
.rangebar .b95 { opacity: .18; } .rangebar .b80 { opacity: .32; } .rangebar .b50 { opacity: .55; }
.rangebar .now { position: absolute; top: 0; bottom: 0; width: 3px; margin-left: -1.5px; border-radius: 2px; background: var(--fg); }
.range-ends { display: flex; justify-content: space-between; font-size: 13px; color: var(--muted); }
.chart img { width: 100%; height: auto; display: block; }
.chart-dark { display: none !important; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .chart-light { display: none !important; }
  :root:not([data-theme="light"]) .chart-dark { display: block !important; } }
:root[data-theme="dark"] .chart-light { display: none !important; }
:root[data-theme="dark"] .chart-dark { display: block !important; }
.years { display: grid; grid-template-columns: auto 1fr 40px; gap: 6px 10px; align-items: center; font-size: 14px; }
.years .y { color: var(--muted); }
.years .track { height: 8px; border-radius: 999px; background: var(--fill); overflow: hidden; }
.years .track span { display: block; height: 100%; border-radius: 999px; background: var(--orange); }
.years .v { text-align: right; }
.calib { width: 100%; border-collapse: separate; border-spacing: 4px; text-align: center; font-size: 16px; }
.calib th { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .02em; color: var(--muted); }
.calib tbody th, .calib tr th:first-child { text-align: left; color: var(--fg); font-size: 15px; text-transform: none; }
.calib td { padding: 8px 0; border-radius: 10px; background: var(--fill); font-weight: 600; }
.calib td.narrow { background: color-mix(in srgb, var(--orange) 22%, transparent); color: var(--orange); }
.calib td.wide { background: var(--blue-soft); color: var(--blue); }
.calib-key { display: flex; gap: 6px 16px; flex-wrap: wrap; color: var(--muted); }
.calib-key > span { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.calib-key .key { width: 12px; height: 12px; border-radius: 4px; }
.key.narrow { background: color-mix(in srgb, var(--orange) 40%, transparent); } .key.wide { background: var(--blue-soft); }
#lock form { display: flex; flex-direction: column; gap: 12px; }
#lock label.check { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 15px; }
#err { min-height: 1.4em; font-size: 15px; color: var(--red); }
footer { color: var(--muted); font-size: 13px; line-height: 1.4; padding: 4px 4px 0; }
@media (max-width: 600px) { .hero-value { font-size: 36px; } }
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Risk Tracker">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="theme-color" content="#f2f2f7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icon-180.png">
<link rel="icon" href="icon-180.png">
<title>Risk Tracker</title>
<style>
__GLASS__
__APP__
</style>
</head>
<body>
<div class="ambient" aria-hidden="true"></div>
<div class="wrap">
  <header class="appbar">
    <div class="brand">__BRAND__<span>Risk Tracker</span>__DEMO__</div>
    <button class="capsule" id="lockBtn" type="button" hidden>Lock</button>
  </header>
  <section class="card" id="lock" __LOCK_HIDDEN__>
    <div class="card-head"><h2>Unlock your report</h2></div>
    <div class="card-body">
      <p class="muted">This page is encrypted. Your password unlocks it on this device only.</p>
      <form id="unlock">
        <input class="input" id="pw" type="password" autocomplete="current-password" placeholder="Password" required>
        <label class="check"><input id="remember" type="checkbox"> Remember on this device</label>
        <button class="btn btn-primary btn-big" type="submit">Unlock</button>
        <p id="err" role="alert"></p>
      </form>
    </div>
  </section>
  <main id="app">__PLAIN__</main>
  <footer>__DISCLAIMER__</footer>
</div>
<nav class="tabbar" id="tabbar" role="tablist" __TABS_HIDDEN__>__TABS__</nav>
<script>
const PAYLOAD = __PAYLOAD__;
const KEY = "risk-tracker-password", TAB = "risk-tracker-tab";
const ls = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
  del(k) { try { localStorage.removeItem(k); } catch (e) {} },
};
if (matchMedia("(prefers-reduced-transparency: reduce)").matches) document.documentElement.classList.add("solid");
const $ = (id) => document.getElementById(id);
function show(name) {
  const views = document.querySelectorAll("#app .view");
  if (!views.length) return;
  if (![...views].some((v) => v.dataset.view === name)) name = views[0].dataset.view;
  views.forEach((v) => { v.hidden = v.dataset.view !== name; });
  document.querySelectorAll("#tabbar button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  ls.set(TAB, name);
}
document.querySelectorAll("#tabbar button").forEach((b) => b.addEventListener("click", () => { show(b.dataset.tab); window.scrollTo({ top: 0 }); }));
const b64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
async function decrypt(password) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: b64(PAYLOAD.salt), iterations: PAYLOAD.iter, hash: "SHA-256" },
    base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
  return new TextDecoder().decode(await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(PAYLOAD.iv) }, key, b64(PAYLOAD.ct)));
}
async function unlock(password, remember) {
  $("err").textContent = "Unlocking…";
  try {
    $("app").innerHTML = await decrypt(password);
    $("lock").hidden = true; $("lockBtn").hidden = false; $("tabbar").hidden = false; $("err").textContent = "";
    if (remember) ls.set(KEY, password);
    show(ls.get(TAB) || "today");
  } catch (e) { $("err").textContent = "That password didn't work."; ls.del(KEY); }
}
if (PAYLOAD) {
  $("unlock").addEventListener("submit", (e) => { e.preventDefault(); unlock($("pw").value, $("remember").checked); });
  $("lockBtn").addEventListener("click", () => {
    ls.del(KEY); $("app").innerHTML = ""; $("pw").value = "";
    $("lock").hidden = false; $("lockBtn").hidden = true; $("tabbar").hidden = true;
  });
  const saved = ls.get(KEY);
  if (saved) unlock(saved, true);
} else {
  show(ls.get(TAB) || "today");
}
</script>
</body>
</html>
"""


def _icon_png(path: Path, size: int) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    fig = plt.figure(figsize=(1, 1), dpi=size)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor("#007aff")
    ax.add_patch(FancyBboxPatch((0, 0.5), 1, 0.5, boxstyle="square,pad=0", color="white", alpha=0.12, lw=0))
    ax.plot([0.2, 0.38, 0.52, 0.8], [0.36, 0.54, 0.44, 0.7], color="white", linewidth=size / 22,
            solid_capstyle="round", solid_joinstyle="round")
    fig.savefig(path, dpi=size, facecolor=fig.get_facecolor())
    plt.close(fig)


def build_site(views_html: str, out_dir: str | Path, password: str | None, demo: bool = False) -> Path:
    """Write index.html, manifest and icons. ``password=None`` publishes the views unencrypted."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tabs = "".join(
        f'<button type="button" role="tab" data-tab="{k}" aria-selected="false">{ICONS[k]}<span>{k.title()}</span></button>'
        for k in ("today", "holdings", "market", "history"))
    if password:
        payload, plain, lock_hidden, tabs_hidden = json.dumps(encrypt(views_html, password)), "", "", "hidden"
    else:
        payload, plain, lock_hidden, tabs_hidden = "null", views_html, "hidden", ""
    page = (PAGE.replace("__GLASS__", GLASS_CSS.read_text(encoding="utf-8"))
                .replace("__APP__", APP_CSS)
                .replace("__BRAND__", BRAND)
                .replace("__DEMO__", '<span class="demo">DEMO</span>' if demo else "")
                .replace("__TABS__", tabs)
                .replace("__TABS_HIDDEN__", tabs_hidden)
                .replace("__LOCK_HIDDEN__", lock_hidden)
                .replace("__DISCLAIMER__", html.escape(DISCLAIMER))
                .replace("__PAYLOAD__", payload)
                .replace("__PLAIN__", plain))
    (out / "index.html").write_text(page, encoding="utf-8")
    manifest = {
        "name": "Risk Tracker", "short_name": "Risk Tracker", "start_url": "./", "scope": "./",
        "display": "standalone", "background_color": "#f2f2f7", "theme_color": "#007aff",
        "icons": [{"src": "icon-180.png", "sizes": "180x180", "type": "image/png"},
                  {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }
    (out / "manifest.webmanifest").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for size in (180, 512):
        _icon_png(out / f"icon-{size}.png", size)
    (out / ".nojekyll").write_text("")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    return out / "index.html"
