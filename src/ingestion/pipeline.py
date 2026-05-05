"""Core ingestion pipeline: S3 → chunk → embed → pgvector upsert."""
import json
import logging
import os
from dataclasses import dataclass

import asyncpg
import boto3

from src.ingestion.parser import extract_text

logger = logging.getLogger(__name__)

CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "512"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "64"))
EMBED_BATCH_SIZE = int(os.environ.get("EMBED_BATCH_SIZE", "20"))
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


def embed_batch(bedrock: "boto3.client", texts: list[str]) -> list[list[float]]:
    results: list[list[float]] = []
    for text in texts:
        response = bedrock.invoke_model(
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
    bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    textract = boto3.client("textract", region_name=AWS_REGION)
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
                existing_etag = await conn.fetchval(
                    "SELECT etag FROM ingested_docs WHERE doc_id = $1", doc_id
                )
                if existing_etag == etag:
                    logger.info("Skipping unchanged doc: %s", doc_id)
                    continue

                # Chunk-level resume: find which chunk_ids are already embedded for this doc.
                # chunk_id is deterministic ({doc_id}_{chunk_index}), so we can cheaply
                # filter out already-processed chunks and avoid re-calling Bedrock for them.
                already_embedded: set[str] = {
                    row["chunk_id"]
                    for row in await conn.fetch(
                        "SELECT chunk_id FROM embeddings WHERE doc_id = $1", doc_id
                    )
                }

            raw_bytes = s3.get_object(Bucket=s3_bucket, Key=key)["Body"].read()
            try:
                text = extract_text(
                    s3_key=key, raw_bytes=raw_bytes, s3_bucket=s3_bucket, textract=textract
                )
            except Exception:
                logger.exception("Failed to parse %s, skipping", doc_id)
                continue

            if not text.strip():
                logger.warning("No text extracted from %s, skipping", doc_id)
                continue

            chunks = chunk_text(doc_id, text)
            pending = [c for c in chunks if f"{c.doc_id}_{c.chunk_index}" not in already_embedded]

            logger.info(
                "Doc %s: %d total chunks, %d pending embedding",
                doc_id, len(chunks), len(pending),
            )

            all_embedded = True
            for i in range(0, len(pending), EMBED_BATCH_SIZE):
                batch = pending[i : i + EMBED_BATCH_SIZE]
                try:
                    vectors = embed_batch(bedrock, [c.text for c in batch])
                except Exception:
                    logger.exception(
                        "Embedding failed for doc %s at chunk_index %d — will retry remaining chunks next run",
                        doc_id, batch[0].chunk_index,
                    )
                    all_embedded = False
                    break

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

            # Only seal the ETag once every chunk is in pgvector.
            # A partial failure leaves ETag unsealed so the next run resumes from
            # the first unembedded chunk rather than restarting the whole doc.
            if not all_embedded:
                continue

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
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "ragplatform")
    user = os.environ.get("DB_USER", "ingestion")
    password = os.environ.get("DB_PASSWORD", "")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"
