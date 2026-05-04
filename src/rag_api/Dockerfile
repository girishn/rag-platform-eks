FROM python:3.13-slim AS builder
WORKDIR /app
RUN pip install uv
COPY pyproject.toml .
RUN uv sync --no-dev --no-install-project

FROM python:3.13-slim
WORKDIR /app
RUN useradd -r -u 1001 -g root appuser
COPY --from=builder /app/.venv /app/.venv
COPY src/rag_api ./src/rag_api
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER 1001
EXPOSE 8000
CMD ["uvicorn", "src.rag_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
