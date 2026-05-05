# System Context Diagram

C4 Level 1 view showing the external actors, system boundary, and AWS services that the RAG
Platform depends on. This diagram answers "what does the system interact with?" without describing
internal implementation details.

Application users reach the platform via HTTPS to an **internet-facing ALB** (not VPC Lattice
directly — VPC Lattice is private and handles east-west routing only). Platform admins connect
through **AWS Client VPN with IAM Identity Center** and reach internal tooling (Grafana, LiteLLM
admin UI) via the same VPC Lattice service network, scoped by IAM AuthPolicy.

All pod-to-AWS-service traffic flows via **VPC Interface/Gateway Endpoints** — Bedrock, ECR, S3,
STS, CloudWatch, SSM — so no RAG Platform traffic traverses the internet via NAT Gateway.

```mermaid
C4Context
  title System Context — RAG Platform on EKS

  Person(user, "Application User", "Calls the RAG API via HTTPS to get LLM-powered answers grounded in uploaded documents")
  Person(admin, "Platform Admin", "Manages tenants, budget caps, model routing config, and observability dashboards — kubectl via public EKS endpoint + port-forward for UI; Client VPN + IAM Identity Center for enterprise private-endpoint hardening")

  System_Boundary(platform, "RAG Platform on EKS (ap-southeast-2)") {
    System(alb, "Internet-Facing ALB", "TLS termination via ACM; forwards to VPC Lattice")
    System(rag, "RAG Platform", "Multi-tenant LLM-powered retrieval and generation service running on Amazon EKS; all internal routing via VPC Lattice")
  }

  System_Ext(vpn, "AWS Client VPN", "Enterprise hardening: admin access to private-endpoint-only cluster via IAM Identity Center SSO. Dev workflow uses public EKS endpoint + kubectl + port-forward instead — no VPN required.")
  System_Ext(bedrock, "AWS Bedrock", "Claude 3.5 Sonnet (LLM) + Titan Embeddings V2 + Guardrails — primary inference backend; reached via VPC Interface Endpoint")
  System_Ext(s3, "Amazon S3", "Raw document storage, chunked text, embedding metadata, and vLLM model weights; SSE-KMS encrypted; TLS-only bucket policy")
  System_Ext(rds, "Amazon RDS (PostgreSQL)", "pgvector for HNSW vector similarity search; per-tenant schema isolation; KMS encrypted; SSL required")
  System_Ext(cw, "Amazon CloudWatch", "Metrics ingestion, X-Ray distributed traces, alerting; reached via VPC Interface Endpoint")
  System_Ext(ecr, "Amazon ECR", "Private container registry for RAG API, ingestion, and LiteLLM images; reached via VPC Interface Endpoint")
  System_Ext(kms, "AWS KMS", "Customer-managed keys for etcd secrets, RDS, S3 at-rest encryption, EBS volumes")
  System_Ext(trail, "AWS CloudTrail", "Audit log: IAM role assumptions, KMS key usage, S3 data access, EKS API calls")

  Rel(user, alb, "POST /v1/chat/completions", "HTTPS / TLS via ACM")
  Rel(alb, rag, "Forward to VPC Lattice", "HTTP/2 private")
  Rel(admin, vpn, "Connect via IAM Identity Center", "HTTPS / mTLS")
  Rel(vpn, rag, "Access Grafana, LiteLLM admin, kubectl", "Private VPC — IAM AuthPolicy enforced")
  Rel(rag, bedrock, "LLM inference + embeddings + guardrails", "VPC Interface Endpoint — no internet")
  Rel(rag, s3, "Read documents; pull model weights", "VPC Gateway Endpoint — no internet")
  Rel(rag, rds, "Vector similarity search; metadata reads", "PostgreSQL TLS — private subnet")
  Rel(rag, cw, "Emit metrics and traces", "VPC Interface Endpoint — no internet")
  Rel(rag, ecr, "Pull container images at deploy", "VPC Interface Endpoint — no internet")
  Rel(rag, kms, "Decrypt secrets; envelope encryption", "VPC Interface Endpoint")
  Rel(rag, trail, "API calls audited automatically", "CloudTrail")
```
