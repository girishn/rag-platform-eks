import logging

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.rag_api.services import embedding, llm_client, retrieval

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    stream: bool = True
    tenant_id: str = ""


@router.post("/chat/completions")
async def chat_completions(
    request: ChatRequest,
    x_tenant_id: str = Header(default=""),
) -> StreamingResponse:
    tenant_id = x_tenant_id or request.tenant_id
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-Id header required")

    user_query = next(
        (m.content for m in reversed(request.messages) if m.role == "user"), ""
    )
    if not user_query:
        raise HTTPException(status_code=400, detail="No user message found")

    logger.info(
        "Chat request received",
        extra={"tenant_id": tenant_id, "model": request.model, "query_len": len(user_query)},
    )

    query_vector = await embedding.embed(user_query)
    logger.info("Embedding complete", extra={"tenant_id": tenant_id, "vector_dims": len(query_vector)})

    chunks = await retrieval.retrieve(query_vector, tenant_id=tenant_id, top_k=5)
    logger.info("Retrieval complete", extra={"tenant_id": tenant_id, "chunks_returned": len(chunks)})

    context = "\n\n".join(f"[{i+1}] {c}" for i, c in enumerate(chunks))
    system_prompt = (
        "You are a helpful assistant. Answer based on the context provided. "
        "If the answer is not in the context, say so.\n\nContext:\n" + context
    )

    messages = [{"role": "system", "content": system_prompt}] + [
        {"role": m.role, "content": m.content} for m in request.messages
    ]

    stream = await llm_client.stream_completion(
        model=request.model, messages=messages, tenant_id=tenant_id
    )
    logger.info("Streaming response started", extra={"tenant_id": tenant_id, "model": request.model})
    return StreamingResponse(stream, media_type="text/event-stream")
