# Container Diagram

C4 Level 2 view showing the internal services, data stores, and their relationships within
the RAG Platform boundary. Each box represents a separately deployable unit (Kubernetes Deployment,
CronJob, or managed AWS service).

The diagram uses two horizontal rows inside the EKS boundary to separate concerns and keep
edges directional: the **query path** (top row) handles real-time requests; the **ingestion and
observability** path (bottom row) handles background pipeline and monitoring.

**Routing split:** ALB connects directly to the RAG API, bypassing VPC Lattice on the external
streaming path. VPC Lattice (Gateway API Controller) handles admin routing only (Grafana) and
internal service policy enforcement. This avoids VPC Lattice's 1-minute idle timeout, which
is incompatible with SSE streaming for long LLM responses.

Prometheus scrapes `/metrics` from all services (RAG API, LiteLLM, vLLM) — this scrape-back
relationship is omitted from the diagram to avoid backwards edges cluttering the layout.

```mermaid
flowchart LR
    User([Application User])
    Admin([Platform Admin])

    subgraph pub["Public"]
        ALB[ALB · ACM TLS]
        VPN[Client VPN · IAM IdC]
    end

    subgraph eks["Amazon EKS · Private Subnets"]
        subgraph qpath["Query path"]
            direction LR
            Lattice[VPC Lattice\nGateway API]
            RAG[RAG API\nFastAPI · Python 3.13]
            LiteLLM[LiteLLM Proxy\nOpenAI-compatible]
            vLLM[vLLM · A10G\nLlama 3.1 8B]
        end

        subgraph opspath["Ingestion · Observability"]
            direction LR
            Ingest[Ingestion\nCronJob]
            OTEL[OTEL\nCollector]
            Prom[Prometheus]
            Graf[Grafana]
        end
    end

    subgraph aws["AWS Backend · VPC Endpoints"]
        Bedrock[Bedrock\nClaude 3.5 · Titan V2]
        RDS[(RDS · pgvector\n+ litellm DB)]
        Redis[(ElastiCache\nServerless Redis)]
        S3[(S3\ndocs · weights)]
        CW[CloudWatch\nX-Ray]
    end

    %% External ingress — ALB direct to RAG API (SSE streaming safe)
    User -->|HTTPS| ALB
    ALB --> RAG

    %% Admin path — VPC Lattice for non-streaming internal access only
    Admin --> VPN
    VPN --> Lattice

    %% Query path
    RAG --> LiteLLM
    RAG -->|embed + guardrails| Bedrock
    RAG -->|ANN search| RDS
    RAG -->|traces| OTEL
    LiteLLM -->|primary| Bedrock
    LiteLLM -->|fallback| vLLM
    LiteLLM -->|key cache + spend| Redis
    LiteLLM -->|key metadata + spend flush| RDS
    LiteLLM -->|traces| OTEL

    %% Admin observability access
    Lattice --> Graf

    %% Observability outputs
    OTEL --> CW
    Prom --> Graf

    %% Ingestion pipeline
    Ingest --> S3 & Bedrock & RDS

    %% vLLM model weights
    vLLM --> S3
```
