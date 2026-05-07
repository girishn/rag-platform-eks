# Source Conventions

## Python
- Type hints on all function signatures — no exceptions
- No bare `except` — always catch specific exception types
- `uv add <pkg>` for dependencies, never `pip install`
- Python 3.13

## Testing
- `pytest` + `moto` for AWS service mocking
- Tests in `src/<component>/tests/`
- LLM mocking: OpenAI-compatible stub or local vLLM in CI
- `uv run scripts/test.py` — full suite
- `uv run scripts/test.py src/rag_api/tests/test_foo.py::bar` — single test
- Local K8s: `kind` for admission webhook and operator tests

## Linting
- `uv run scripts/lint.py` — ruff check + mypy
- `uv run scripts/fmt.py` — ruff format
