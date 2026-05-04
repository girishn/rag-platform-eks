# Container Diagram

C4 Level 2 view showing the internal services, data stores, and their relationships within
the RAG Platform boundary. Each box represents a separately deployable unit (Kubernetes Deployment,
CronJob, or managed AWS service).

```mermaid
C4Container
  title Container Diagram — RAG Platform on EKS

  Person(user, "Application User")
  Person(admin, "Platform Admin")

  System_Boundary(eks, "Amazon EKS Cluster") {
    Container(gateway, "AWS VPC Lattice Gateway", "Gateway API Controller", "Routes external HTTPS traffic to internal services via HTTPRoute")
    Container(rag_api, "RAG API", "FastAPI / Python 3.13", "Query rewriting, embedding, retrieval, prompt assembly, guardrails, streaming response")
    Container(litellm, "LiteLLM Proxy", "Python / Docker", "OpenAI-compatible router: Bedrock primary, vLLM fallback; virtual key budget enforcement")
    Container(vllm, "vLLM", "Python / GPU (A10G)", "Self-hosted Llama 3.1 8B inference; PagedAttention; OpenAI-compatible API")
    Container(ingestion, "Ingestion Pipeline", "Kubernetes CronJob / Python", "S3 → chunk → Titan embed → pgvector upsert")
    Container(otel, "OTEL Collector", "OpenTelemetry", "Receives traces from all services; forwards to CloudWatch X-Ray and Grafana Tempo")
    Container(prometheus, "Prometheus", "kube-prometheus-stack", "Scrapes /metrics from all services; feeds Grafana and AlertManager")
    Container(grafana, "Grafana", "Grafana OSS", "Dashboards: cost, latency, GPU utilisation, routing split, per-tenant spend")
  }

  System_Ext(bedrock, "AWS Bedrock", "Claude 3.5 + Titan Embeddings + Guardrails")
  System_Ext(s3, "Amazon S3", "Documents + model weights")
  System_Ext(rds, "Amazon RDS / pgvector", "Per-tenant vector + metadata storage")
  System_Ext(cw, "CloudWatch", "X-Ray traces + metrics")

  Rel(user, gateway, "POST /v1/chat/completions", "HTTPS")
  Rel(admin, grafana, "View dashboards", "HTTPS")
  Rel(gateway, rag_api, "HTTPRoute match", "HTTP/2")
  Rel(rag_api, bedrock, "Embed query (Titan)", "AWS SDK")
  Rel(rag_api, rds, "ANN vector search", "PostgreSQL")
  Rel(rag_api, litellm, "POST /v1/chat/completions", "HTTP")
  Rel(litellm, bedrock, "Primary route — Claude 3.5", "AWS SDK")
  Rel(litellm, vllm, "Fallback route — Llama 3.1 8B", "HTTP")
  Rel(vllm, s3, "Pull model weights (init container)", "AWS SDK")
  Rel(ingestion, s3, "Read raw documents", "AWS SDK")
  Rel(ingestion, bedrock, "Titan embed chunks", "AWS SDK")
  Rel(ingestion, rds, "Upsert vectors", "PostgreSQL")
  Rel(rag_api, otel, "Export traces", "OTLP gRPC")
  Rel(litellm, otel, "Export traces", "OTLP gRPC")
  Rel(otel, cw, "Forward X-Ray traces", "AWS SDK")
  Rel(prometheus, rag_api, "Scrape /metrics", "HTTP")
  Rel(prometheus, litellm, "Scrape /metrics", "HTTP")
  Rel(prometheus, vllm, "Scrape /metrics", "HTTP")
  Rel(prometheus, grafana, "Query metrics", "PromQL")
```
