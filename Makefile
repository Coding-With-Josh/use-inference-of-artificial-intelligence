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
	@echo "demo-mock: not yet implemented (docs+skeleton only)"

study1-plan:
	@echo "study1-plan: not yet implemented"

study1-run:
	@echo "study1-run: not yet implemented"

study1-analyze:
	@echo "study1-analyze: not yet implemented"

tasks-validate:
	uv run python -m pilot.tasks.validate

study2-demo:
	@echo "study2-demo: not yet implemented"

clean:
	rm -rf build dist .pytest_cache .mypy_cache .ruff_cache htmlcov
	find . -name "__pycache__" -type d -exec rm -rf {} +
	find . -name "*.pyc" -delete
