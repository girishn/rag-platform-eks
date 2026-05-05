# Multi-Tenancy Isolation Model

Graph showing the three-layer tenant isolation model: Kubernetes namespace (compute),
PostgreSQL schema (data), and LiteLLM virtual key (budget). Each layer is independently
enforceable. See [ADR-007](../adr/ADR-007-multi-tenant-isolation-model.md) for the decision rationale.

```mermaid
graph LR
    subgraph EKS["EKS Cluster"]
        subgraph NSA["Namespace: tenant-alpha"]
            PodA[RAG API Pod\ntenant=alpha]
            NPA[NetworkPolicy\nAllow: ingress from Gateway\nDeny: cross-tenant]
        end
        subgraph NSB["Namespace: tenant-beta"]
            PodB[RAG API Pod\ntenant=beta]
            NPB[NetworkPolicy\nAllow: ingress from Gateway\nDeny: cross-tenant]
        end
        subgraph NSSys["Namespace: rag-platform (shared)"]
            LiteLLM[LiteLLM Proxy]
            GW[VPC Lattice Gateway]
        end
    end

    subgraph RDS["RDS PostgreSQL"]
        SchemaA[(Schema: tenant_alpha\ntable: embeddings\ntable: documents\ntable: sessions)]
        SchemaB[(Schema: tenant_beta\ntable: embeddings\ntable: documents\ntable: sessions)]
    end

    subgraph LiteLLMKeys["LiteLLM Budget Enforcement"]
        KeyA[Virtual Key: alpha-key\nmax_budget: $100/month\nrpm_limit: 60]
        KeyB[Virtual Key: beta-key\nmax_budget: $500/month\nrpm_limit: 300]
    end

    PodA -- "search_path=tenant_alpha" --> SchemaA
    PodB -- "search_path=tenant_beta" --> SchemaB
    PodA -- "Authorization: Bearer alpha-key" --> LiteLLM
    PodB -- "Authorization: Bearer beta-key" --> LiteLLM
    LiteLLM --> KeyA
    LiteLLM --> KeyB
    GW --> PodA
    GW --> PodB

    style NSA fill:#e8f4fd,stroke:#2196f3
    style NSB fill:#fde8f4,stroke:#e91e8c
    style SchemaA fill:#e8f4fd,stroke:#2196f3
    style SchemaB fill:#fde8f4,stroke:#e91e8c
    style KeyA fill:#e8f4fd,stroke:#2196f3
    style KeyB fill:#fde8f4,stroke:#e91e8c
```
