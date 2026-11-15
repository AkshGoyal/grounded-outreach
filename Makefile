.PHONY: install test lint fmt check

install:            ## Create the venv and install the exact versions in uv.lock
	uv sync --locked --extra dev

test:               ## Run the suite. Needs no API keys and no network.
	uv run pytest

lint:               ## Check formatting and lint rules without changing files
	uv run ruff check .
	uv run ruff format --check .

fmt:                ## Apply formatting and auto-fixable lint rules
	uv run ruff format .
	uv run ruff check --fix .

check: lint test    ## What to run before committing
