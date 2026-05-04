# LLM Routing Decision Tree

Flowchart showing how LiteLLM Proxy routes each request: budget check first, then primary
(Bedrock), then fallback (vLLM). Budget exhaustion and backend errors are distinct failure
modes — budget exhaustion does NOT trigger the fallback chain.

```mermaid
flowchart TD
    A[Incoming request\nPOST /v1/chat/completions\nwith tenant virtual key] --> B{Virtual key\nbudget check}

    B -- "Over budget\n(max_budget exceeded)" --> E[429 Budget Exceeded\nReturn error to caller\nDo NOT route to any backend]

    B -- "Within budget" --> C{Route to primary\nAWS Bedrock\nClaude 3.5 Sonnet}

    C -- Success --> D[Return response\nIncrement spend counter\nLog token usage]

    C -- "ThrottlingException\nor 5xx error" --> F{Retry count\n< max_retries = 2?}

    F -- "Yes\n(exponential backoff)" --> C

    F -- "No\n(retries exhausted)" --> G{Route to fallback\nvLLM on EKS\nLlama 3.1 8B}

    G -- Success --> H[Return response\nLog fallback_triggered=true\nEmit fallback counter metric]

    G -- "Error\n(vLLM unavailable\nor OOM)" --> I[503 Both backends unavailable\nReturn error — never silently drop]

    D --> J[Emit metrics:\nrequests_total, tokens_total\nlatency_p99, backend=bedrock]
    H --> K[Emit metrics:\nrequests_total, tokens_total\nlatency_p99, backend=vllm\nfallback_events_total++]

    style E fill:#f96,stroke:#c00
    style I fill:#f96,stroke:#c00
    style D fill:#6c6,stroke:#090
    style H fill:#fa6,stroke:#c60
```
