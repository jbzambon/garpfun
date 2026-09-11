# garp

A GARP (growth at a reasonable price) screener and point-in-time backtest
harness for small-cap equities. This is a **research tool, not a trading
system** — the goal is to find out honestly whether the strategy has any
edge, including the possibility that it doesn't.

See [`SPEC.md`](SPEC.md) for the full design and the non-negotiable
principles this project is built around (point-in-time data, no
survivorship bias, no restated data, determinism), and
[`KNOWN_BIASES.md`](KNOWN_BIASES.md) for the running bias register that
every backtest result must be read alongside.

## Status

Phase 0 (scaffolding) and Phase 1 (data layer: SEC EDGAR fundamentals,
prices + corporate actions) are done. No factor logic, universe
construction, or backtest yet — see SPEC.md for the phase plan.

## Setup

Requires [`uv`](https://docs.astral.sh/uv/).

```sh
make sync              # install dependencies into .venv
make precommit-install  # install git pre-commit hooks
make check              # lint + typecheck + test
```

Fetching real data (`make data` / `garp data`) requires a SEC EDGAR contact
identifier. Copy `.env.example` to `.env` (gitignored, never committed) and
fill in `GARP_SEC_CONTACT` — see that file and `garp.config` for why this
isn't optional.

## Layout

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

## Commands

```sh
make data       # Phase 1: fetch and cache raw data (implemented)
make universe   # Phase 2: build the point-in-time universe panel
make factors    # Phase 3: compute factor scores
make backtest   # Phase 4: run the walk-forward backtest
make screen     # Phase 5: today's ranked candidate list
make report     # Phase 5: HTML/markdown report with bias register attached
```

`universe`, `factors`, `backtest`, `screen`, and `report` each raise
`NotImplementedError` pointing at the SPEC.md phase that implements them.

`data` ingests a specific, small set of names to develop against (Phase 2
is what will drive it at scale):

```sh
uv run garp data --tickers KLIC,OXM --start 2015-01-01
uv run garp data --ciks 320193                    # by CIK instead of ticker
uv run garp data                                  # refreshes the CIK<->ticker map only
```
