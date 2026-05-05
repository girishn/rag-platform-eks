# ADR-001: Custom RAG Pipeline over Bedrock Knowledge Bases or Framework Abstraction

**Date:** 2026-05-05
**Status:** Accepted
**Deciders:** Girish Narayanan

## Context

The platform needs a RAG (Retrieval-Augmented Generation) pipeline: a system that takes a user
query, retrieves relevant document chunks from a vector store, assembles a prompt, and routes it
to an LLM. AWS offers Bedrock Knowledge Bases as a fully managed option. Open-source frameworks
(LlamaIndex, LangChain, Haystack) offer abstractions over the same components.

This is the foundational decision — it determines whether all subsequent decisions (vector store,
LLM router, ingestion pipeline, tenant isolation model) are even necessary. If Bedrock Knowledge
Bases had been chosen, most other ADRs in this series would not exist.

## Decision

Build a custom RAG pipeline in FastAPI + Python. Use AWS services (Bedrock, RDS/pgvector, S3)
directly via their SDKs. Do not use Bedrock Knowledge Bases. Do not introduce a RAG framework
dependency (LlamaIndex, LangChain, Haystack).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| **AWS Bedrock Knowledge Bases** | Fully managed; zero ingestion infrastructure; fast to start | Locked to Bedrock models — no vLLM fallback possible; 50 KB hard limit per account; shared KMS key across tenants in single-KB model; vector store is OpenSearch Serverless (~$700+/month minimum); no per-tenant spend caps; limited observability |
| **LlamaIndex** | Purpose-built for RAG data ingestion; wide connector ecosystem; advanced retrieval patterns (hybrid, reranking) | ~6ms framework overhead per request; additional dependency to pin and upgrade; abstractions obscure what the pipeline is actually doing |
| **LangChain** | Widest adoption; large ecosystem; fast prototyping | ~10ms framework overhead; reputation for abstraction complexity in production; general-purpose, not RAG-optimised |
| **Haystack (deepset)** | Production-grade; modular pipeline contracts; strong evaluation tooling; enterprise support | Heavier framework footprint; less AWS-native; adds operational surface for a team already managing EKS |
| **Custom FastAPI + SDK** | Zero framework overhead; full control of retrieval, chunking, routing; observable at every step; pipeline is ~200 lines and readable | Must implement plumbing (batching, retry, upsert deduplication) that frameworks provide; no built-in evaluation tooling |

## Consequences

**Easier:**
- Dual-backend LLM routing (Bedrock → vLLM fallback) is straightforward — the pipeline calls
  LiteLLM directly. Bedrock Knowledge Bases has no equivalent mechanism.
- Per-tenant isolation via PostgreSQL schemas scales to any number of tenants with no service
  limits. Bedrock KB's per-tenant model is one KB per tenant, capped at 50 per account.
- Every pipeline step (embedding call, vector query, prompt assembly, LLM call) is a measurable
  OTEL span and Prometheus metric. Nothing is a black box.
- Chunking strategy, overlap, batch size, and HNSW parameters are configurable env vars.
  Bedrock KB's custom chunking requires a Lambda function per chunk.
- pgvector on RDS costs ~$50–80/month at this scale vs OpenSearch Serverless at ~$700+/month.

**Harder:**
- Ingestion infrastructure must be built and operated (CronJob, S3 reader, chunker, embedder).
  Bedrock KB handles this with a sync API call.
- No built-in evaluation framework. Retrieval recall, chunk quality, and answer accuracy require
  custom test harnesses. Haystack provides this out of the box.
- Advanced retrieval patterns (hybrid search, reranking, HyDE) must be implemented rather than
  configured. LlamaIndex has these as first-class features.

**What this decision does not prevent:**
- Adding LlamaIndex or Haystack later for evaluation tooling or advanced retrieval, without
  replacing the core pipeline.
- Adding Bedrock Knowledge Bases as a second retrieval backend if a use case arises that fits
  its model (e.g. a tenant with simple, low-volume needs).

## References

- [AWS Bedrock Knowledge Bases — 50 KB account limit](https://repost.aws/questions/QUq5_BeCo-Sd2rJ7SGZG0hPA/amazon-bedrock-knowledge-base-limit-of-50-knowledge-base)
- [Multi-tenancy in Bedrock Knowledge Bases](https://aws.amazon.com/blogs/machine-learning/multi-tenant-rag-with-amazon-bedrock-knowledge-bases/)
- [RAG framework overhead benchmarks 2025](https://langcopilot.com/posts/2025-09-18-top-rag-frameworks-2024-complete-guide)
- [ADR-002](ADR-002-llm-routing-strategy.md) — LiteLLM routing (only relevant because this ADR chose custom)
- [ADR-003](ADR-003-vector-database-selection.md) — pgvector (only relevant because this ADR chose custom)
