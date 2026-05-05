# Observability Pipeline

Flowchart showing the full observability pipeline: metric sources, collection layer, and
destinations. Covers the four golden signals (latency, traffic, errors, saturation) and
distributed tracing through to CloudWatch X-Ray.

```mermaid
flowchart LR
    subgraph Sources["Metric Sources"]
        A["RAG API\n/metrics\n(latency, retrieval hits, errors)"]
        B["LiteLLM\n/metrics + /spend/logs\n(token spend, routing split, fallback rate)"]
        C["vLLM\n/metrics\n(num_requests_waiting, gpu_cache_usage_perc, tokens/s)"]
        D["DCGM Exporter\nGPU metrics\n(gpu_utilization, gpu_memory_used)"]
        E["kube-state-metrics\n(pod restarts, node status)"]
    end

    subgraph Collection["Collection Layer"]
        F["Prometheus\nScrape + TSDB storage\n15s interval"]
        G["ADOT Collector\nOTLP receiver → X-Ray exporter\nW3C TraceContext propagation"]
    end

    subgraph Destinations["Destinations"]
        H["Grafana\nDashboards:\n• Cost per tenant\n• Latency P50/P95/P99\n• GPU utilisation\n• Bedrock vs vLLM split\n• Error rates"]
        I["CloudWatch\nX-Ray distributed traces\n(RAG API → LiteLLM → Bedrock spans)"]
        J["AlertManager\n→ PagerDuty / Slack\nAlerts:\n• waiting_requests > 10\n• gpu_cache > 90%\n• error_rate > 1%\n• fallback_triggered"]
    end

    A --> F
    B --> F
    C --> F
    D --> F
    E --> F
    F --> H
    F --> J

    A --> G
    B --> G
    G --> I

    style Sources fill:#f5f5f5,stroke:#999
    style Collection fill:#e8f4e8,stroke:#4caf50
    style Destinations fill:#e8eaf6,stroke:#3f51b5
```
