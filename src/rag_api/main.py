from fastapi import FastAPI
from prometheus_client import make_asgi_app

from src.rag_api.routers import chat

app = FastAPI(title="RAG Platform API", version="0.1.0")

app.include_router(chat.router)

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
