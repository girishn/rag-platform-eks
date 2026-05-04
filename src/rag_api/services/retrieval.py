import asyncpg
from src.rag_api.config import settings

_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=settings.db_host,
            port=settings.db_port,
            database=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
        )
    return _pool


async def retrieve(
    query_vector: list[float],
    *,
    tenant_id: str,
    top_k: int = 5,
) -> list[str]:
    pool = await _get_pool()
    schema = f"tenant_{tenant_id.replace('-', '_')}"
    vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    async with pool.acquire() as conn:
        await conn.execute(f"SET search_path = {schema}")
        rows = await conn.fetch(
            f"""
            SELECT chunk_text
            FROM embeddings
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            vector_str,
            top_k,
        )
    return [row["chunk_text"] for row in rows]
