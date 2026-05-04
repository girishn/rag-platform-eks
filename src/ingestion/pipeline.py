"""Core ingestion pipeline: S3 → chunk → embed → pgvector upsert."""
import json
import logging
from dataclasses import dataclass

import asyncpg
import boto3

logger = logging.getLogger(__name__)

CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
EMBED_BATCH_SIZE = 20
AWS_REGION = "ap-southeast-2"
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"


@dataclass
class Chunk:
    doc_id: str
    chunk_index: int
    text: str


def chunk_text(doc_id: str, text: str) -> list[Chunk]:
    words = text.split()
    chunks: list[Chunk] = []
    start = 0
    idx = 0
    while start < len(words):
        end = min(start + CHUNK_SIZE, len(words))
        chunks.append(Chunk(doc_id=doc_id, chunk_index=idx, text=" ".join(words[start:end])))
        start += CHUNK_SIZE - CHUNK_OVERLAP
        idx += 1
    return chunks


def embed_batch(texts: list[str]) -> list[list[float]]:
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    results: list[list[float]] = []
    for text in texts:
        response = client.invoke_model(
            modelId=EMBEDDING_MODEL_ID,
            body=json.dumps({"inputText": text}),
            contentType="application/json",
            accept="application/json",
        )
        body = json.loads(response["body"].read())
        results.append(body["embedding"])
    return results


async def run_pipeline(*, tenant_id: str, s3_bucket: str, s3_prefix: str) -> None:
    s3 = boto3.client("s3", region_name=AWS_REGION)
    schema = f"tenant_{tenant_id.replace('-', '_')}"

    db_url = _db_url_from_env()
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=5)

    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=s3_bucket, Prefix=s3_prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            etag = obj["ETag"].strip('"')
            doc_id = key.replace(s3_prefix, "").replace("/", "_")

            async with pool.acquire() as conn:
                await conn.execute(f"SET search_path = {schema}")
                existing = await conn.fetchval(
                    "SELECT etag FROM ingested_docs WHERE doc_id = $1", doc_id
                )
                if existing == etag:
                    logger.info("Skipping unchanged doc: %s", doc_id)
                    continue

            body = s3.get_object(Bucket=s3_bucket, Key=key)["Body"].read().decode("utf-8")
            chunks = chunk_text(doc_id, body)
            logger.info("Chunked %s into %d chunks", doc_id, len(chunks))

            for i in range(0, len(chunks), EMBED_BATCH_SIZE):
                batch = chunks[i : i + EMBED_BATCH_SIZE]
                vectors = embed_batch([c.text for c in batch])

                async with pool.acquire() as conn:
                    await conn.execute(f"SET search_path = {schema}")
                    for chunk, vector in zip(batch, vectors):
                        chunk_id = f"{doc_id}_{chunk.chunk_index}"
                        vector_str = "[" + ",".join(str(v) for v in vector) + "]"
                        await conn.execute(
                            """
                            INSERT INTO embeddings (chunk_id, doc_id, chunk_text, embedding)
                            VALUES ($1, $2, $3, $4::vector)
                            ON CONFLICT (chunk_id) DO UPDATE
                            SET chunk_text = EXCLUDED.chunk_text,
                                embedding = EXCLUDED.embedding
                            """,
                            chunk_id, doc_id, chunk.text, vector_str,
                        )

            async with pool.acquire() as conn:
                await conn.execute(f"SET search_path = {schema}")
                await conn.execute(
                    """
                    INSERT INTO ingested_docs (doc_id, etag, ingested_at)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (doc_id) DO UPDATE
                    SET etag = EXCLUDED.etag, ingested_at = EXCLUDED.ingested_at
                    """,
                    doc_id, etag,
                )

    await pool.close()


def _db_url_from_env() -> str:
    import os
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "ragplatform")
    user = os.environ.get("DB_USER", "ingestion")
    password = os.environ.get("DB_PASSWORD", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"
