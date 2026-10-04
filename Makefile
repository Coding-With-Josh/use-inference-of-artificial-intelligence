.PHONY: install test lint typecheck sandbox-image demo-mock study1-plan study1-run study1-analyze tasks-validate study2-demo clean

install:
	uv sync --dev

sandbox-image:
	docker build --tag pilot-sandbox:latest --file sandbox/Dockerfile sandbox

test:
	uv run pytest

lint:
	uv run ruff check .

typecheck:
	uv run mypy src tests

demo-mock:
	uv run pilot demo-mock

study1-plan:
	uv run pilot study1-plan

study1-run:
	uv run pilot study1-run

study1-analyze:
	uv run pilot study1-analyze

tasks-validate:
	uv run python -m pilot.tasks.validate

study2-demo:
	uv run pilot study2-randomize && uv run pilot study2-ingest && uv run pilot study2-analyze

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache htmlcov
	find . -name "__pycache__" -type d -exec rm -rf {} +
	find . -name "*.pyc" -delete
