# System Context Diagram

C4 Level 1 view showing the external actors, system boundary, and AWS services that the RAG
Platform depends on. This diagram answers "what does the system interact with?" without describing
internal implementation details.

```mermaid
C4Context
  title System Context — RAG Platform on EKS

  Person(user, "Application User", "Calls the RAG API via HTTPS to get LLM-powered answers grounded in uploaded documents")
  Person(admin, "Platform Admin", "Manages tenants, budget caps, model routing config, and observability dashboards")

  System_Boundary(platform, "RAG Platform on EKS (ap-southeast-2)") {
    System(rag, "RAG Platform", "Multi-tenant LLM-powered retrieval and generation service running on Amazon EKS")
  }

  System_Ext(bedrock, "AWS Bedrock", "Claude 3.5 Sonnet (LLM) + Titan Embeddings V2 + Guardrails — primary inference backend")
  System_Ext(s3, "Amazon S3", "Raw document storage, chunked text, embedding metadata, and vLLM model weights")
  System_Ext(rds, "Amazon RDS (PostgreSQL)", "pgvector for HNSW vector similarity search; per-tenant schema isolation")
  System_Ext(cw, "Amazon CloudWatch", "Metrics ingestion, X-Ray distributed traces, alerting")
  System_Ext(ecr, "Amazon ECR", "Private container registry for RAG API, ingestion, and LiteLLM images")

  Rel(user, rag, "POST /v1/chat/completions", "HTTPS / AWS VPC Lattice")
  Rel(admin, rag, "Manage tenants, keys, dashboards", "HTTPS")
  Rel(rag, bedrock, "LLM inference + embeddings + guardrails", "AWS SDK / HTTPS")
  Rel(rag, s3, "Read documents; pull model weights", "AWS SDK")
  Rel(rag, rds, "Vector similarity search; metadata reads", "PostgreSQL wire protocol")
  Rel(rag, cw, "Emit metrics and traces", "OTEL / CloudWatch API")
  Rel(rag, ecr, "Pull container images at deploy", "HTTPS")
```
