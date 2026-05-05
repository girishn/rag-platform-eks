# RAG Query Request Flow

End-to-end sequence diagram for a single RAG query, from the client HTTP request through vector
retrieval, prompt assembly, LLM routing, and streaming response. Shows both the Bedrock success
path and the vLLM fallback path.

```mermaid
sequenceDiagram
    participant C as Client
    participant A as ALB (ACM TLS · idle_timeout=300s)
    participant R as RAG API (FastAPI)
    participant P as pgvector (RDS)
    participant L as LiteLLM Proxy
    participant Redis as ElastiCache Redis
    participant B as AWS Bedrock
    participant V as vLLM (EKS GPU)
    participant ADOT as ADOT Collector

    C->>A: HTTPS POST /v1/chat/completions
    A->>R: HTTP — direct to RAG API pod (SSE streaming safe)

    %% Query embedding
    R->>B: Titan embed(query_text)
    B-->>R: query_vector [1536 dims]

    %% Vector retrieval
    R->>P: SELECT chunk_text, metadata ORDER BY embedding <=> query_vector LIMIT 5
    P-->>R: top-k chunks + similarity scores

    %% Prompt assembly
    R->>R: Assemble system prompt + context chunks + user query

    %% LLM routing — key validation via Redis cache
    R->>L: POST /v1/chat/completions (assembled prompt + tenant virtual key)
    L->>Redis: GET key_hash (budget + RPM metadata)
    Redis-->>L: cached key metadata (or cache miss → query litellm DB on RDS)
    L->>L: Validate budget + RPM — within limit

    alt Bedrock available
        L->>B: InvokeModelWithResponseStream — Claude 3.5 Sonnet
        B-->>L: Streaming completion tokens
        L-->>R: SSE token stream
    else Bedrock ThrottlingException or 5xx
        L->>L: Retry 2× with exponential backoff
        L->>V: POST /v1/chat/completions — Llama 3.1 8B (fallback)
        V-->>L: Streaming completion tokens
        L-->>R: SSE token stream (logged as fallback event)
    end

    R-->>C: Streamed response (SSE)

    %% Async observability + spend tracking
    R-)ADOT: OTLP span export (end-to-end trace, embedding latency, retrieval latency)
    L-)ADOT: OTLP span export (routing decision, token count, backend selected)
    L-)Redis: INCRBYFLOAT spend (tenant_id, tokens, cost) — atomic increment
    L-)P: Flush spend to litellm DB — batched async (periodic)
```
