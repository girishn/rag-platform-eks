from typing import AsyncIterator
import httpx
from src.rag_api.config import settings


async def stream_completion(
    *,
    model: str,
    messages: list[dict[str, str]],
    tenant_id: str,
) -> AsyncIterator[bytes]:
    headers = {
        "Authorization": f"Bearer {settings.litellm_api_key}",
        "X-Tenant-Id": tenant_id,
    }
    payload = {"model": model, "messages": messages, "stream": True}

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            f"{settings.litellm_base_url}/v1/chat/completions",
            json=payload,
            headers=headers,
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                yield chunk
