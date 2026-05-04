# Architecture Decision Records

This directory contains all ADRs for the RAG Platform on EKS. ADRs are the primary record of
**why** the system is built the way it is. Once Accepted, an ADR is never edited — if a decision
changes, a new ADR supersedes the old one.

## Index

| ADR | Title | Status | Date |
|---|---|---|---|
| [ADR-001](ADR-001-llm-routing-strategy.md) | LiteLLM as dual-provider LLM router (Bedrock primary, vLLM fallback) | Accepted | 2026-05-04 |
| [ADR-002](ADR-002-vector-database-selection.md) | pgvector on RDS PostgreSQL as the vector store | Accepted | 2026-05-04 |
| [ADR-003](ADR-003-gateway-api-controller.md) | AWS Gateway API Controller (VPC Lattice) over Kong or Envoy Gateway | Accepted | 2026-05-04 |
| [ADR-004](ADR-004-eks-pod-identity-over-irsa.md) | EKS Pod Identity over IRSA for application workload IAM | Accepted | 2026-05-04 |
| [ADR-005](ADR-005-vllm-model-serving.md) | vLLM over SageMaker or Triton for self-hosted GPU inference | Accepted | 2026-05-04 |
| [ADR-006](ADR-006-multi-tenant-isolation-model.md) | Three-layer tenant isolation model (namespace + schema + virtual key) | Accepted | 2026-05-04 |

## How to write an ADR

1. Copy `_template.md` to `ADR-NNN-short-slug.md`
2. Write the ADR **before** implementing — articulating the decision forces understanding
3. Add a row to this index
4. Once Accepted, never edit — supersede with a new ADR if the decision changes
