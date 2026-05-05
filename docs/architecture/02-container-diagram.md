# Container Diagram

C4 Level 2 view showing the internal services, data stores, and their relationships within
the RAG Platform boundary. Each box represents a separately deployable unit (Kubernetes Deployment,
CronJob, or managed AWS service).

The diagram uses two horizontal rows inside the EKS boundary to separate concerns and keep
edges directional: the **query path** (top row) handles real-time requests; the **ingestion and
observability** path (bottom row) handles background pipeline and monitoring.

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
        RDS[(RDS · pgvector)]
        S3[(S3\ndocs · weights)]
        CW[CloudWatch\nX-Ray]
    end

    %% Ingress
    User -->|HTTPS| ALB
    Admin --> VPN
    ALB & VPN --> Lattice

    %% Query path
    Lattice --> RAG
    RAG --> LiteLLM
    RAG -->|embed + guardrails| Bedrock
    RAG -->|ANN search| RDS
    RAG -->|traces| OTEL
    LiteLLM -->|primary| Bedrock
    LiteLLM -->|fallback| vLLM
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
