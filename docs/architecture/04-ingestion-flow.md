# Document Ingestion Pipeline Flow

Sequence diagram for the document ingestion CronJob: reading raw documents from S3, chunking,
embedding via Titan, and upserting into the pgvector index. Runs on a schedule and is idempotent
(re-ingesting the same document updates the existing vector, it does not create a duplicate).

```mermaid
sequenceDiagram
    participant S as Amazon S3 (raw docs)
    participant J as Ingestion CronJob (Kubernetes)
    participant B as AWS Bedrock (Titan Embeddings)
    participant P as pgvector (RDS)

    Note over J: CronJob triggered by Kubernetes scheduler

    J->>S: List objects in tenant prefix (tenant_id/raw/)
    S-->>J: Object keys + ETags

    J->>P: SELECT doc_id, etag FROM tenant_schema.ingested_docs
    P-->>J: Already-ingested ETags

    loop For each new or changed object
        J->>S: GetObject (raw document bytes)
        S-->>J: Document content

        J->>J: Chunk document (fixed-size + overlap, ~512 tokens)

        loop For each chunk (batched, 20 at a time)
            J->>B: InvokeModel — Titan Embeddings V2 (batch)
            B-->>J: Embedding vectors [1536 dims each]
        end

        J->>P: INSERT INTO tenant_schema.embeddings ON CONFLICT (chunk_id) DO UPDATE SET embedding = EXCLUDED.embedding
        P-->>J: Upsert confirmed

        J->>P: UPSERT tenant_schema.ingested_docs (doc_id, etag, ingested_at)
    end

    Note over J: Emit Prometheus counter: chunks_ingested_total, embedding_errors_total
```
