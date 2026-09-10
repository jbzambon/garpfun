.PHONY: sync data universe factors backtest screen report test lint typecheck check fmt precommit-install clean

UV := uv

sync:  ## Install/lock dependencies
	$(UV) sync

data: sync  ## Fetch and cache raw data (Phase 1)
	$(UV) run garp data

universe: sync  ## Build the point-in-time universe panel (Phase 2)
	$(UV) run garp universe

factors: sync  ## Compute factor scores (Phase 3)
	$(UV) run garp factors

backtest: sync  ## Run the walk-forward backtest (Phase 4)
	$(UV) run garp backtest

screen: sync  ## Produce today's ranked candidate list (Phase 5)
	$(UV) run garp screen --asof today

report: sync  ## Render the HTML/markdown report with bias register (Phase 5)
	$(UV) run garp report

test: sync  ## Run the test suite
	$(UV) run pytest

lint: sync  ## Lint with ruff
	$(UV) run ruff check .
	$(UV) run ruff format --check .

typecheck: sync  ## Type-check with mypy
	$(UV) run mypy src

check: lint typecheck test  ## Run everything CI runs

fmt: sync  ## Auto-format and auto-fix lint issues
	$(UV) run ruff check --fix .
	$(UV) run ruff format .

precommit-install: sync  ## Install git pre-commit hooks
	$(UV) run pre-commit install

clean:  ## Remove caches and build artifacts (never touches data/)
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build *.egg-info
