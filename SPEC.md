# GARP Screener & Backtest Harness — Project Spec

> Paste this whole file into Claude Code as the initial prompt, or save it as
> `SPEC.md` in an empty repo and start with: *"Read SPEC.md and implement Phase 0."*

---

## Context for the assistant

I'm rebuilding a stock screener I wrote ~6 years ago in Python. The old version
scraped Zacks for PEG/estimates, screened the Russell 2000, and emitted tickers
under $50/share. It was a candidate generator with no backtest, so I never knew
if it worked.

This rebuild is a **research tool, not a trading system**. The point is to find
out whether a GARP screen on small caps has any edge after honest accounting for
survivorship bias, look-ahead bias, and transaction costs. A negative result is a
valid and useful outcome. Do not tune the strategy until it looks good.

I am an experienced Python developer (scientific computing background) but new to
quantitative finance tooling. Explain finance-specific decisions; don't explain
Python.

---

## Non-negotiable principles

These are the reason the project exists. Violating them silently is the single
worst failure mode, so enforce them in code and in tests, not just in comments.

1. **Point-in-time everything.** A backtest on date `T` may only use data that
   was publicly available on or before `T`. Fundamentals must be keyed on
   *filing date*, never period-end date. A Q4 result with a period-end of
   Dec 31 that was filed Feb 20 is not knowable on Jan 15.

2. **No survivorship bias.** The universe on date `T` must include companies
   that later went bankrupt, got acquired, or were delisted. If a data source
   can't provide delisted securities, that is a known defect and must be
   recorded in `KNOWN_BIASES.md` with an estimate of its direction and rough
   magnitude — not quietly ignored.

3. **No restated data.** Use as-reported figures. Restatements leak the future
   into the past.

4. **Every result carries its caveats.** Any backtest output — plot, table,
   summary — must be accompanied by the bias register that applies to it.

5. **Deterministic and reproducible.** Same inputs, same code, same numbers.
   Seed everything. Cache raw downloads immutably; never mutate a raw file in
   place.

---

## Phase 0 — Scaffolding

Set up before writing any strategy logic.

- Python 3.12+, `uv` for dependency management (or `pdm` if you prefer, but pick
  one and pin a lockfile).
- Layout:
  ```
  data/raw/          # immutable downloads, gitignored, content-addressed
  data/interim/      # parsed but unjoined
  data/processed/    # analysis-ready parquet
  src/garp/
    ingest/          # one module per data source
    universe/        # constituent construction
    factors/         # factor computation
    backtest/        # engine
    report/          # output
  tests/
  notebooks/         # exploration only, nothing load-bearing
  KNOWN_BIASES.md
  ```
- Storage: parquet via `polars` (preferred) or `pandas` + `pyarrow`.
- `pytest`, `ruff`, `mypy` in strict-ish mode. Pre-commit hooks.
- A `Makefile` or `justfile` with `make data`, `make backtest`, `make report`.
- Structured logging (`structlog`). Every data fetch logs source, URL, retrieval
  timestamp, and a hash of the payload.

Create `KNOWN_BIASES.md` in this phase with a table: bias, where it enters,
direction of effect, magnitude estimate, mitigation status. Append to it as you
go — it should never be empty.

---

## Phase 1 — Data layer

The hard part. Budget most of your time here.

### Fundamentals — SEC EDGAR (free, genuinely point-in-time)

Use the **SEC Financial Statement Data Sets** (quarterly ZIPs of parsed XBRL)
and/or the `companyfacts` / `companyconcept` JSON API.

Why these: each record carries the accession number and **filing date**, which
is exactly what principle #1 needs. Most commercial "historical fundamentals"
products are restated and period-end-keyed, which quietly breaks the backtest.

Implementation notes:
- Identity key is **CIK**, not ticker. Tickers get reused and reassigned.
  Maintain a CIK ↔ ticker ↔ date-range mapping table.
- Respect SEC's rate limits and set a real User-Agent with a contact address.
- Handle amended filings (10-K/A): the amendment is knowable only from *its*
  filing date, not the original's.
- Normalize the XBRL tag chaos. Companies use different tags for the same
  concept and change tags between years. Build an explicit concept-mapping
  layer with a fallback chain per concept, and log unmapped cases rather than
  filling with nulls.

Concepts needed at minimum: revenue, net income, diluted EPS, shares
outstanding, total assets, total liabilities, total debt, cash and equivalents,
operating cash flow, capex, shareholders' equity.

### Prices

Start with whatever is cheapest and be explicit about the tradeoff:
- `yfinance` — free, easy, **survivorship-biased** (delisted tickers vanish).
  Fine for Phase 1 plumbing; not acceptable for final results.
- Tiingo / Polygon / Financial Modeling Prep free or low tiers — better,
  varying delisting coverage.
- Nasdaq Data Link (Sharadar SEP/SFP) — paid but modest cost, includes
  delisted securities. If the project graduates past a toy, this is the upgrade.

Whichever source: store **unadjusted** prices plus a separate corporate-actions
table (splits, dividends), and compute adjustments at query time. Pre-adjusted
price series are another quiet look-ahead vector.

### Forward estimates — read this before designing around them

The "growth" leg of classic GARP uses forward EPS estimates and PEG. There is
**no free point-in-time source of analyst estimates**. Consensus estimates are
revised constantly, and vendors typically serve you the current snapshot, which
is catastrophic for a backtest.

Options, in order of preference:
1. Drop forward estimates entirely. Use realized trailing growth (3–5yr revenue
   and EPS CAGR from EDGAR) as the growth leg. Fully point-in-time, no vendor.
   **Default to this.**
2. Use forward estimates for the *live screen only*, never the backtest, and
   label the backtest as testing a related-but-different strategy.
3. Pay for a PIT estimates product (I/B/E/S, Refinitiv) — out of scope.

Implement option 1. Make the growth leg pluggable so option 2 can be added
later without touching the engine.

---

## Phase 2 — Universe construction

Default universe: **S&P SmallCap 600**, not the Russell 2000.

Rationale: the S&P 600 requires positive earnings for index inclusion, which
removes the large unprofitable cohort that makes PEG-style screens misbehave on
the Russell 2000. Make the universe swappable so I can run Russell 2000 as a
comparison.

Construction rules:
- Rebuild the universe **monthly**, using only information available that month.
- Point-in-time constituent lists are genuinely hard to get free. Acceptable
  fallback: build a synthetic universe from all EDGAR filers, ranked by market
  cap into a band (e.g. ranks 1001–2000 by market cap on the rebalance date),
  with liquidity and price filters. Document this substitution prominently — a
  synthetic universe is not the S&P 600 and will diverge.
- Filters applied at universe level: minimum 60-day median dollar volume
  (start at $1M/day), minimum price $3 (microstructure noise, not a valuation
  view), US primary listing, exclude ADRs, exclude REITs and financials
  initially (their accounting breaks most ratio-based factors — revisit later
  with sector-specific handling).
- **No share-price ceiling.** Share price is an artifact of share count, not an
  economic variable. If a size constraint is wanted, it belongs on market cap,
  where it already is.

Output: a `(date, cik, ticker)` panel, one row per security per rebalance date,
including securities that later delist.

---

## Phase 3 — Factor computation

Compute each factor as an independent, individually testable function over the
point-in-time panel. Signature roughly
`f(panel: pl.DataFrame, asof: date) -> pl.Series`.

**Value leg**
- Earnings yield (inverse P/E), trailing twelve months
- EV/EBIT
- Free cash flow yield

**Growth leg**
- 3yr and 5yr revenue CAGR
- 3yr and 5yr diluted EPS CAGR
- Growth *stability*: standard deviation of YoY growth. Erratic growth that
  averages out well is not the same as steady compounding, and the classic
  PEG screen can't tell them apart.

**Quality leg** — this is where the old screener was weakest and where the
value-trap protection lives
- Return on invested capital
- Gross profitability (gross profit / total assets)
- Accruals (the gap between net income and operating cash flow — large positive
  accruals are the standard earnings-quality red flag)
- Net debt / EBITDA
- Interest coverage
- Share count trend (persistent dilution is a quiet return killer in small caps)
- Piotroski F-Score as a composite sanity check

**Composite**
- Cross-sectional z-score each factor **within sector**, winsorize at 1st/99th
  percentile, then combine. Sector-neutral scoring prevents the screen from
  becoming an unintentional sector bet.
- Make weights configurable via a YAML config, defaulting to equal weight
  across the three legs. Do not hand-tune weights against backtest results.

Compute a classic PEG as well, purely so I can compare the old approach against
the composite.

---

## Phase 4 — Backtest harness

Vectorized, monthly rebalance, long-only.

- Portfolio: top N by composite score (default N=30), equal-weighted.
- Entry at next day's open after signal date. No same-bar fills.
- Transaction costs: commission (default 0) plus a slippage model that scales
  with the position's share of median daily volume. Small caps are where naive
  backtests lie most — a 5% ADV order does not fill at the midpoint.
- **Delisting handling.** When a holding delists: acquisitions settle at the
  deal price; bankruptcies go to zero. Getting this wrong is the single largest
  source of fake alpha in small-cap backtests. Make the delisting-return
  assumption an explicit, logged parameter.
- Benchmark against IJR (S&P 600) and IWM (Russell 2000), plus an equal-weight
  version of the same universe so I can see whether the edge comes from the
  factors or just from equal-weighting.

Outputs: CAGR, volatility, Sharpe, Sortino, max drawdown, drawdown duration,
turnover, hit rate, average holding period, and factor-attribution decomposition
(how much of the return is explained by market/size/value exposure versus
something unexplained).

### Validation — build this at the same time as the engine, not after

- **Walk-forward only.** No in-sample parameter fitting.
- **Deflated Sharpe ratio**, tracking how many strategy variants have been
  tested. If I run 50 configurations, the best one looks good by construction;
  the deflated statistic is what tells me whether it's real.
- **Null tests.** Run the engine on randomly-selected portfolios from the same
  universe, 1000 times, and report where the real strategy falls in that
  distribution. If it's inside the noise band, say so plainly.
- **Regime splits.** Report performance separately across rate regimes and
  across small-cap-leading versus large-cap-leading periods. A strategy that
  only works in one regime is a bet on that regime.

---

## Phase 5 — Live screen and report

- `garp screen --asof today` produces a ranked candidate list with every factor
  value shown, not just the composite — I want to see *why* something ranked.
- HTML or markdown report with the bias register attached.
- Flag any candidate whose data is stale (no filing in >120 days) or thinly
  covered.

---

## Working style

- Implement one phase at a time. Stop and show me the output before moving on.
- Write the test alongside the code, especially for the point-in-time joins —
  those are the bugs that will silently invent alpha.
- When a data source can't support a principle above, say so explicitly and
  offer the honest degraded option rather than working around it quietly.
- If a backtest result looks too good, treat that as a bug report and go
  looking for the leak before celebrating. In this domain, suspiciously good
  numbers are almost always a defect.
