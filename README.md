# stock-risk-tracker

A small, honest risk monitor for a beginner investor in Singapore holding a few US securities
(default: **VT** and **AAPL**).

It **describes** risk: how bumpy prices have been, how wide a month of moves has historically been,
how a loss-limit rule would have played out from every past entry date, and how each of your
positions is doing against **your own** rules. It also checks itself: a walk-forward test shows how
often its own ranges were wrong.

It **does not** predict price direction, does not produce buy/sell signals, does not connect to a
broker and never trades.

> Educational only, not financial advice. Past data does not guarantee future results.

## What it reports

| Section | What you get |
|---|---|
| What this means for you | Plain sentences about your own money in SGD:<br>- what your holdings are worth<br>- what today's move cost or added<br>- what a normal and a bad month have looked like for your holding<br>- how far you are from your loss limit, with your own sell rule quoted back<br>- earnings coming up, sized to your holding<br>- the VT comparison<br>- the currency effect<br>Fixed templates: it never says what to do. |
| Volatility | Daily returns, 20- and 60-day rolling volatility (daily and annualised), typical daily move (median absolute return), 52-week range, and where today's volatility sits in its own history. |
| Earnings moves (AAPL) | Average and largest move on past earnings reaction days, compared with a typical day, plus days until the next expected earnings date (if yfinance provides one). |
| 1-month ranges | 50% / 80% / 95% price bands from 10,000 bootstrapped 21-day paths of past daily returns. Labelled **"historical ranges, not predictions"**. |
| Loss-limit backtest | For **every** historical entry date: did the price close at or below the loss limit within 3 months, what was the worst drawdown, and how did "exit at the limit" compare with simply holding (fees included)? Also shown by entry year. |
| Journal | Your `positions.csv`: P/L in USD and SGD, distance to the loss limit, fees paid, and your return compared with holding VT since the same date. |
| Alerts | A daily move beyond your threshold (default 2 SD), earnings within 7 days, or a price within 3% of (or below) your loss limit. |
| Out-of-sample range check | A walk-forward test of the bands with no lookahead: did the "80%" band really contain the price 80% of the time? Split by calm and volatile periods and by ticker, with a calibration chart and a plain-language verdict. |

Outputs:
- a terminal summary
- `reports/YYYY-MM-DD.md`
- PNG charts in `charts/YYYY-MM-DD/`
- the raw walk-forward rows in `reports/YYYY-MM-DD-walk-forward.csv`
- optionally, a password-protected web page for your phone (see below)

## Setup

Requires Python 3.11+.

```bash
cd stock-risk-tracker
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp positions.example.csv positions.csv   # then put your own trades in positions.csv
```

`positions.csv` is in `.gitignore`, so your real journal is never committed by accident.

No API key is needed: data comes from Yahoo Finance via `yfinance`.

## Usage

```bash
python -m risk_tracker report                  # full daily report (downloads/uses the cache)
python -m risk_tracker report --no-calibration # faster: skip the walk-forward check
python -m risk_tracker report --no-charts
python -m risk_tracker fetch                   # only download/refresh the cache
python -m risk_tracker report --offline        # never touch the network; cache only
python -m risk_tracker report --refresh        # ignore cache age and re-download
python -m risk_tracker report --demo           # SYNTHETIC data, no network: try the tool safely
python -m risk_tracker report --config my.yaml
SITE_PASSWORD='a long passphrase' python -m risk_tracker report --site site   # also build the web page
```

`pip install -e .` also installs a `stock-risk-tracker` command with the same options.

**Caching.** Prices are saved as CSV in `data/cache/`. A run within `cache_max_age_hours` (default 12)
of the last download reuses the cache. If a download fails, the tool falls back to the stale cache
and says so in the report. Earnings dates are cached for 24 hours. The yfinance earnings feed often
breaks; when it does, the earnings section is skipped and everything else still runs.

**Demo mode.** `--demo` generates regime-switching synthetic prices (calm and volatile spells, fat
tails, earnings-day jumps for "AAPL"). Every demo report, chart and file name is marked
**SYNTHETIC**. Demo output describes the method, never real securities.

### config.yaml

```yaml
tickers: [VT, AAPL]
benchmark: VT            # positions are compared with simply holding this
fx_ticker: USDSGD=X
history_years: 10
loss_limit_pct: -15
fee_per_trade_usd: 0.99
alert_threshold_sd: 2.0
earnings_tickers: [AAPL]
bands:       {horizon_days: 21, levels: [0.5, 0.8, 0.95], n_sims: 10000, seed: 42}
backtest:    {horizon_days: 63, position_usd: 1000}
calibration: {min_history_days: 252, step_days: 5, n_sims: 2000}
```

### positions.csv (your journal)

One row per buy trade:

```csv
ticker,buy_date,buy_price,shares,reason,what_would_prove_me_wrong,sell_rule
AAPL,2025-01-15,233.00,4,Like the ecosystem,Services revenue shrinks two years running,Sell if down 15% or thesis breaks
```

An optional `loss_limit_pct` column overrides the config limit for that row. The trades in
`positions.example.csv` are illustrative; put your own in `positions.csv`.

How the numbers are defined:
- **P/L USD** = (current price - buy price) x shares, minus the buy fee.
- **P/L SGD** = today's value at today's USDSGD rate, minus what you paid at the USDSGD rate on the
  buy date. This includes currency gains and losses.
- **Loss-limit distance** = how far the current price is above `buy_price x (1 + limit)`.
- **Fees paid** = one flat fee per row (the buy). Sell fees are not counted until you sell.
- **vs VT** = your return minus VT's price return since the same date. Dividends are excluded for
  both, so the comparison is like for like.

## Web app on your iPhone (free, with GitHub Pages)

A free GitHub Actions job builds the report every weekday at about 06:15 Singapore time, after the US
close, and publishes it at `https://<your-username>.github.io/<repo-name>/`. No server or domain is
needed.

**Privacy.**
- Free GitHub Pages sites are public, so the page is **encrypted**: AES-256-GCM, with the key derived
  from your password by PBKDF2-SHA256 with 600,000 iterations.
- The published file contains only scrambled data. Your browser decrypts it locally after you type
  the password; the password never leaves your device.
- Your journal is stored as an encrypted GitHub **secret**, never as a file in the repo.
- Both secrets are optional. With neither set, you get a market-only page with no lock, since there
  is nothing private on it.
- Use a long passphrase (at least 12 characters; 4-5 random words is good). Anyone can download the
  encrypted page and try to guess it offline.

**One-time setup**
1. Create a GitHub account. Create a new repository (Public is fine; Private needs a paid plan for
   Pages) and push this project to it:
   ```bash
   git remote add origin https://github.com/<you>/stocks-tracker.git
   git push -u origin main
   ```
2. *(Optional, can be done later)* In the repo, go to **Settings → Secrets and variables → Actions →
   New repository secret** and add:
   - `SITE_PASSWORD`: your passphrase. It locks the page.
   - `POSITIONS_CSV`: paste the full contents of your `positions.csv`, including the header line.
     Update this secret whenever you trade.

   What happens with each combination:

   | Secrets set | What gets published |
   |---|---|
   | Neither | A **market-only** page with no lock: volatility, earnings, ranges, backtest, honesty check. No personal data. |
   | Both | The full page, including your positions and "What this means for you", **encrypted**. |
   | Password only | The market-only page, encrypted. |
   | Journal only | **Nothing.** The run stops with an error, so your holdings are never published unlocked. |
3. Go to **Settings → Pages → Build and deployment → Source**, choose **GitHub Actions**.
4. Go to **Actions → Daily risk report → Run workflow** to build it now. After that it runs on its
   own each weekday.

**On your iPhone**
1. Open the page in **Safari** and enter your passphrase. Tick "Remember on this device" if you
   don't want to type it each time.
2. Tap **Share → Add to Home Screen**. It now opens full-screen like an app.

The same page works on a Mac or Android browser.

**If a day's run fails** (for example, Yahoo Finance rate-limits GitHub's servers), the page keeps
showing the previous report and GitHub emails you. Downloaded prices are cached between runs, so
temporary outages fall back to the last good data and say so in the report.

**Optional custom domain.** `github.io` is free and enough. If you want your own name, a domain costs
about US$10-15 a year; add it under Settings → Pages → Custom domain.

## Tests

```bash
python -m pytest -q
```

All tests use synthetic data; none needs a network connection. They cover:
- **Volatility:** exact returns, rolling vol recovering a known sigma, median-absolute move, NaN handling.
- **Bands:** nesting, width matching theory for i.i.d. returns, reproducibility, resampling only observed returns.
- **Backtest:** every entry date tested, hit detection (including gaps through the limit), drawdown from peak, fees.
- **Walk-forward:**
  - A **leak test** randomly corrupts every price after date *t*; the bands and regime labels at
    or before *t* must not change, while the realised outcome must.
  - Bands at *t* equal a bootstrap on history truncated at *t*.
  - On i.i.d. data the bands are calibrated.
  - On regime-switching data they break in volatile periods.
- **Data layer:** cache reuse, stale-cache fallback on network errors, flaky earnings feed, offline mode.
- **Journal and alerts:** P/L in USD and SGD, weekend buy dates, alert rules.
- **"What this means for you":** amounts in SGD, your own rules quoted, currency effect split out,
  and no advice wording.
- **Web page:**
  - Encryption round trip and wrong-password rejection.
  - Your journal text never appears unencrypted in the published file.
  - The build refuses to run without a strong password.
- **End-to-end:** the report ends with the disclaimer and contains no trading-signal wording.

## How the out-of-sample check works

1. On every 5th trading day *t* (after the first year), rebuild the 50/80/95% bands using **only
   prices up to and including *t***.
2. Look up the actual price 21 trading days later and record whether it fell inside each band, and
   whether misses were above or below.
3. Label *t* as **calm** or **volatile**: trailing 20-day volatility below or above the median of all
   trailing readings up to *t*. This label also uses only past data.
4. Compare hit rates with the stated levels. A tolerance accounts for overlapping 1-month windows
   (only about 1 in 4 checks is independent when stepping 5 days with a 21-day horizon). The verdict
   is "too narrow", "too wide" or "about right".

## Limitations (read this)

**What the calibration check shows.** The bands resample daily returns from the whole history, as if
every day were drawn from the same unchanging distribution. Real markets are not like that:
volatility clusters, so calm spells and turbulent spells each tend to persist.

The walk-forward check is built to expose exactly this weakness. On the synthetic demo data, which
has volatility clustering by design, the results were:

- **VT (demo):** about right overall (50/80/95% bands held 53/82/94%), and within tolerance in both
  calm and volatile periods.
- **AAPL (demo):**
  - About right overall (55/78/91%).
  - **Too narrow in volatile periods** (47/68/86%): the "80%" band missed about one time in three.
  - Too wide in calm periods (63/89/96%).

Good average calibration hid poor calibration in exactly the conditions where it matters most.

These figures come from synthetic data, not real markets. The development environment could not
reach Yahoo Finance, so this README contains no real-data results. Run
`python -m risk_tracker report` and read the "Verdict in plain language" in your own report.
Expect the same pattern on real data: bands that are too narrow in turbulent periods (for example
2020 or 2022) and too wide in quiet ones. Treat the 95% band as "a loss outside this happens more
often than 1 in 40 months", not as a floor.

Other limitations:
- **History is not a forecast.** Ten years of data includes few true crises. A move worse than
  anything in the sample is always possible, and the bootstrap can never produce one.
- **No memory between days.** I.i.d. resampling ignores momentum, mean reversion and volatility
  clustering. That is a deliberate choice: this is a description, not a model.
- **Earnings jumps are mixed in.** For AAPL, about 4 earnings days a year are averaged into the
  daily pool. A month that contains an earnings date is riskier than the band suggests.
- **Closing prices only.** The backtest ignores intraday lows. A real stop order could trigger on an
  intraday dip that recovers by the close, and gaps can exit well below the limit (the table shows
  this).
- **Overlapping windows.** The backtest and calibration counts use overlapping periods, so they
  contain far fewer independent observations than rows. One bad year can dominate; check the
  by-year table.
- **Data quality.** yfinance is unofficial and can break, return gaps or change adjusted prices
  after the fact. Earnings dates in particular are unreliable. Dividend-adjusted prices are used for
  returns and quoted prices for P/L.
- **Not covered:** taxes (including US dividend withholding for Singapore residents), FX conversion
  spreads, platform fees beyond the flat per-trade fee, and position sizing.

---

*This project is for educational purposes only and is not financial advice. Past data does not
guarantee future results.*
