FROM python:3.13-slim AS builder
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
RUN uv sync --no-dev --no-install-project

FROM python:3.13-slim
WORKDIR /app
RUN useradd -r -u 1001 -g root appuser
COPY --from=builder /app/.venv /app/.venv
COPY src/ingestion ./src/ingestion
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 1001
CMD ["python", "-m", "src.ingestion.main"]
