# RAG Query Request Flow

End-to-end sequence diagram for a single RAG query, from the client HTTP request through vector
retrieval, prompt assembly, LLM routing, and streaming response. Shows both the Bedrock success
path and the vLLM fallback path.

```mermaid
sequenceDiagram
    participant C as Client
    participant G as Gateway (VPC Lattice)
    participant R as RAG API (FastAPI)
    participant P as pgvector (RDS)
    participant L as LiteLLM Proxy
    participant B as AWS Bedrock
    participant V as vLLM (EKS GPU)

    C->>G: POST /v1/chat/completions
    G->>R: HTTPRoute match → forward

    %% Query embedding
    R->>B: Titan embed(query_text)
    B-->>R: query_vector [1536 dims]

    %% Vector retrieval
    R->>P: SELECT chunk_text, metadata ORDER BY embedding <=> query_vector LIMIT 5
    P-->>R: top-k chunks + similarity scores

    %% Prompt assembly + guardrails
    R->>R: Assemble system prompt + context chunks + user query
    R->>B: Bedrock Guardrails — apply content filter
    B-->>R: Filtered / approved prompt

    %% LLM routing
    R->>L: POST /v1/chat/completions (assembled prompt + tenant virtual key)
    L->>L: Check virtual key budget — within limit

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

    %% Async observability
    R-)L: Emit OTEL span (end-to-end latency, token count)
    L-)P: Log spend record (tokens, cost, tenant_id)
```
