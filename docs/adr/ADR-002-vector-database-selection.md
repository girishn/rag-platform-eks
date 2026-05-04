# ADR-002: pgvector on RDS PostgreSQL as the Vector Store

**Date:** 2026-05-04
**Status:** Accepted
**Deciders:** Girish Narayanan

## Context

The RAG pipeline requires a vector store that can perform approximate nearest-neighbour (ANN)
search over embedding vectors, support multi-tenant data isolation, and integrate cleanly with
the existing AWS infrastructure. The platform targets a baseline of ~1M document chunks across
all tenants at launch, with expected growth to ~10M over 12 months.

## Decision

Use pgvector on RDS PostgreSQL (Aurora-compatible engine) with an HNSW index. Each tenant gets
an isolated PostgreSQL schema (`tenant_{id}`). The vector dimension is 1536 (Titan Embeddings v2).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| pgvector on RDS | Managed PostgreSQL, HNSW index (fast ANN), schema-level multi-tenancy, no extra service to operate, AWS-native IAM auth | Not purpose-built for vectors; single-node read scaling (requires read replica for high QPS) |
| OpenSearch with k-NN plugin | AWS managed, horizontal scaling, full-text hybrid search | ~3× more expensive at baseline load; operationally heavier; hybrid ranking more complex to tune |
| Weaviate (self-hosted on EKS) | Purpose-built vector DB, built-in multi-tenancy, rich filtering | Another stateful workload to operate; backups, upgrades, HA — not worth the overhead at this scale |
| Pinecone (managed) | Zero-ops, fast, purpose-built | SaaS; data leaves AWS; per-vector pricing becomes expensive at 10M+ vectors; no schema-level isolation |

## Consequences

**Easier:**
- Multi-tenancy via schema isolation is a single `SET search_path` call — no application-layer
  sharding logic required.
- RDS handles backups, Multi-AZ failover, and minor version upgrades.
- Existing PostgreSQL operational knowledge applies directly.

**Harder:**
- HNSW index parameters (`m`, `ef_construction`, `ef_search`) must be tuned per use case.
  Wrong defaults cause either slow inserts or poor recall.
- Changing embedding model (and therefore vector dimension) requires dropping and rebuilding the
  index — there is no online migration path for HNSW with a dimension change.
- At >10M vectors per tenant, query latency may require read replicas or pgvector partitioning.

**Risks:**
- pgvector is not purpose-built; at very high scale (100M+ vectors) a dedicated vector DB
  would be reconsidered. ADR-002 should be revisited at 50M vector milestone.

## References

- [pgvector HNSW indexing](https://github.com/pgvector/pgvector#hnsw)
- [Amazon Titan Embeddings V2 dimensions](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html)
- [pgvector benchmarks vs Weaviate](https://ann-benchmarks.com/)
