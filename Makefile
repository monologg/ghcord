setup: set-dev set-precommit
quality: check-quality check-lock
style: set-style
test: set-test

set-dev:
	uv sync --frozen

set-precommit:
	uv run --frozen --only-group quality pre-commit install

set-test:
	uv run --frozen pytest --cov=app --cov-report=term-missing tests/

set-style:
	uv run --frozen --only-group quality ruff check --fix .
	uv run --frozen --only-group quality ruff format .

check-quality:
	uv run --frozen --only-group quality ruff check .
	uv run --frozen --only-group quality ruff format --check .

check-lock:
	uv lock --check
