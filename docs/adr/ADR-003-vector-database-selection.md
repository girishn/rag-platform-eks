# ADR-002: pgvector on RDS PostgreSQL as the Vector Store

**Date:** 2026-05-04
**Status:** Accepted
**Deciders:** Girish Narayanan

## Context

The RAG pipeline requires a vector store that can perform approximate nearest-neighbour (ANN)
search over embedding vectors, support multi-tenant data isolation, and integrate cleanly with
the existing AWS infrastructure. The platform targets a baseline of ~1M document chunks across
all tenants at launch, with expected growth to ~10M over 12 months.

The vector store is queried on every RAG request (embedding lookup is in the critical path), so
query latency and metadata filtering accuracy directly affect user-facing response time and answer
quality.

## Decision

Use pgvector on RDS PostgreSQL with an HNSW index. Each tenant gets an isolated PostgreSQL schema
(`tenant_{id}`). The vector dimension is 1536 (Titan Embeddings V2).

pgvector was chosen over S3 Vectors primarily because of **filtered query recall degradation** in
S3 Vectors when metadata filters are applied — a known issue (documented in AWS forums, measured at
~10–40% recall drop) that is unacceptable for a multi-tenant RAG system where tenant isolation
relies on per-query filtering. pgvector's SQL `WHERE` clauses have no such penalty, and the
schema-per-tenant model eliminates cross-tenant filtering entirely.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| pgvector on RDS (chosen) | Managed PostgreSQL; HNSW ANN with no relevancy penalty under filtering; schema-level tenant isolation; no extra service; SQL `WHERE` for hybrid search | Fixed instance cost (~$104/month db.t3.large); single-node read scaling; HNSW rebuild required on embedding model change |
| **Amazon S3 Vectors** | Serverless, cheapest at low query volume (~$3–6/month at 1M vectors vs ~$104/month RDS); scales to 2B vectors; zero ops; native Bedrock + EKS integration (AWS published reference architecture) | **Filtered query recall drops ~10–40%** when metadata filters applied — deal-breaker for multi-tenant RAG; query latency 100–500 ms vs pgvector's 20–60 ms; no dot product metric; max K=100 per query; no algorithm tuning; query costs accumulate at high QPS |
| OpenSearch with k-NN plugin | AWS managed; horizontal scaling; full-text hybrid search | ~3× more expensive at baseline; operationally heavier; hybrid ranking harder to tune |
| Weaviate (self-hosted on EKS) | Purpose-built; built-in multi-tenancy; rich filtering | Another stateful workload; backups, upgrades, HA — overhead not justified at this scale |
| Pinecone (managed) | Zero-ops; fast; purpose-built | SaaS; data leaves AWS; per-vector pricing expensive at 10M+ vectors; no schema-level isolation |

## S3 Vectors — detailed assessment

S3 Vectors (GA December 2025) is the lowest-cost AWS vector option and has an AWS-published EKS
reference architecture. It warrants serious consideration for this platform, and would be the
**right choice** under different workload assumptions:

**S3 Vectors wins when:**
- Queries are infrequent (<10/tenant/day) and cost is the primary constraint
- You can use **per-tenant indices** (one S3 index per tenant) — this avoids filtered recall
  degradation entirely since no cross-tenant filtering is needed
- Query latency of 100–400 ms is acceptable (batch/async RAG, not conversational chat)
- You want zero infrastructure to operate

**S3 Vectors loses for this platform because:**
1. **Filtered recall degradation** — even with per-tenant S3 indices, queries that filter by
   document type, date, or tag within a tenant's index suffer ~10–40% recall drop. This directly
   reduces RAG answer quality and is the core technical blocker.
2. **Interactive latency** — P95 of 400–1000 ms at 1M vectors is too slow for conversational RAG.
   pgvector P95 is 36–60 ms on a tuned HNSW index.
3. **No algorithm tuning** — `ef_search` controls the recall/latency tradeoff on HNSW. S3 Vectors
   abstracts this away; you cannot tune for your specific recall target.
4. **Max K=100** — insufficient if re-ranking strategies require wider candidate sets.

**Revisit trigger:** If the platform moves to batch/async RAG (not real-time chat), or if the
RDS cost becomes unjustifiable against query volume, revisit S3 Vectors with per-tenant indices
and measure actual filtered recall on the production embedding distribution.

## Consequences

**Easier:**
- Multi-tenancy via schema isolation is a single `SET search_path` call — no application-layer
  sharding logic required.
- RDS handles backups, Multi-AZ failover, and minor version upgrades.
- Existing PostgreSQL operational knowledge applies directly.
- No filtered recall penalty — SQL `WHERE` clauses on metadata columns do not affect ANN accuracy.

**Harder:**
- HNSW index parameters (`m`, `ef_construction`, `ef_search`) must be tuned per use case.
  Wrong defaults cause either slow inserts or poor recall.
- Changing embedding model (and therefore vector dimension) requires dropping and rebuilding the
  index — there is no online migration path for HNSW with a dimension change.
- At >10M vectors per tenant, query latency may require read replicas or pgvector partitioning.
- Fixed RDS instance cost (~$104/month db.t3.large) regardless of query volume — S3 Vectors
  would be significantly cheaper at low query volume.

**Risks:**
- pgvector is not purpose-built; at very high scale (100M+ vectors) a dedicated vector DB
  would be reconsidered. Revisit this ADR at the 50M vector milestone.
- If S3 Vectors resolves its filtered query recall issue (it is a relatively new service), the
  cost argument for switching becomes strong. Monitor AWS changelog.

## References

- [pgvector HNSW indexing](https://github.com/pgvector/pgvector#hnsw)
- [Amazon Titan Embeddings V2 dimensions](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html)
- [Amazon S3 Vectors documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors.html)
- [S3 Vectors GA announcement](https://aws.amazon.com/blogs/aws/amazon-s3-vectors-now-generally-available-with-increased-scale-and-performance/)
- [Building self-managed RAG with EKS and S3 Vectors — AWS blog](https://aws.amazon.com/blogs/storage/building-self-managed-rag-applications-with-amazon-eks-and-amazon-s3-vectors/)
- [S3 Vectors filtered query recall degradation — AWS rePost](https://repost.aws/questions/QUjrm6KygfTBiwaaKpwqY_lQ/filtered-query-relevancy-degradation-in-s3-vectors-and-a-potential-architectural-fix)
- [S3 Vectors latency analysis](https://murraycole.com/posts/aws-s3-vectors-latency-analysis)
- [S3 Vectors pricing deep dive](https://murraycole.com/posts/aws-s3-vectors-pricing-deep-dive)
- [pgvector benchmarks vs alternatives](https://ann-benchmarks.com/)
