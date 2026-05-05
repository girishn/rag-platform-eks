# Design Decisions and Learning Notes

Per-component reasoning, tradeoffs, and observations from building the platform.
Update this file as each component is built. This is a living document.

---

## Infrastructure (Week 1)

### EKS and Karpenter

**NodePool split decision:** Two NodePools (CPU and GPU) rather than one mixed pool because
Karpenter's instance type selection for GPU workloads requires `nvidia.com/gpu` resource requests,
which would conflict with CPU-only workloads over-requesting GPU nodes. Separate pools with
`taints` + `tolerations` ensures GPU nodes are reserved exclusively for vLLM.

**AL2023 vs Bottlerocket:** CPU nodes use AL2023 (familiar tooling, good for troubleshooting
with `kubectl exec`). GPU nodes use Bottlerocket Accelerated — it ships with the NVIDIA container
runtime pre-configured and is hardened for production. Mixing AMI families is intentional here.

**Observations from deliberate exercises:**
- _[Fill in after Week 1 exercises]_ Karpenter provisioning time for g5.xlarge spot: X minutes
- _[Fill in]_ Exact error message when Pod Identity association is deleted: `...`
- _[Fill in]_ Karpenter log pattern for wrong amiFamily: `...`

---

### RDS and pgvector

**HNSW parameter selection:**
- `m = 16`: connectivity per node. Higher m → better recall but more memory. 16 is the
  pgvector default and appropriate for 1536-dim Titan embeddings.
- `ef_construction = 64`: build-time candidate list size. Higher → better index quality but
  slower insert. 64 is a good baseline; increase if recall tests show <0.95 at k=5.
- `ef_search = 40`: query-time candidate list. Tune per latency budget. See pgvector runbook.

**Observations from deliberate exercises:**
- _[Fill in after Week 3]_ Recall at k=3 / k=5 / k=10 with ef_search=40: ...
- _[Fill in]_ p99 query latency at ef_search=20 vs ef_search=40 vs ef_search=80: ...

---

## LLM Serving (Week 2)

### vLLM

**PagedAttention rationale:** Traditional LLM serving pre-allocates KV cache memory per request
at max sequence length, wasting VRAM for short requests. PagedAttention allocates KV cache in
pages dynamically, allowing the A10G's 24GB to serve more concurrent requests efficiently.
This is why `vllm:num_requests_waiting` is the right KEDA scale signal — it measures actual
backpressure, not CPU load.

**Model weight strategy:** Weights in S3, not baked into image. Benefits: image stays small
(~2GB base DLC vs ~18GB with weights), model changes don't require image rebuilds, and S3
versioning provides a rollback path. Cost: 3–5 minute cold start for weight download.

**Observations from deliberate exercises:**
- _[Fill in after Week 2]_ vLLM direct P50/P95/P99 latency: ...
- _[Fill in]_ LiteLLM overhead (vLLM direct vs via LiteLLM): ...
- _[Fill in]_ LiteLLM overhead (Bedrock direct vs via LiteLLM): ...
- _[Fill in]_ OOM failure behaviour: pod restarts after X seconds, Kubernetes CrashLoopBackOff kicks in at Nth restart...

---

### LiteLLM

**Budget vs backend error distinction:** This is the most important operational concept.
A virtual key budget exhaustion returns 429 from LiteLLM and should NOT trigger the fallback
chain — the tenant has spent their allowance. A Bedrock ThrottlingException is a backend error
that SHOULD trigger fallback. LiteLLM's retry/fallback config handles this distinction correctly
by design; the key is understanding it when reading logs.

**Observations from deliberate exercises:**
- _[Fill in after Week 2]_ LiteLLM 429 response body when budget exceeded: `...`
- _[Fill in]_ LiteLLM log line when fallback triggers: `...`

---

## RAG API (Week 3)

### Query pipeline design

**Query rewriting decision:** The RAG API rewrites the user query before embedding (expanding
abbreviations, adding synonyms) to improve retrieval recall. This adds one LLM call per request
but significantly improves recall for short or ambiguous queries. The rewrite uses a lightweight
Haiku call, not the full Sonnet — cost is ~0.1% of the main inference call.

**Guardrails placement:** Bedrock Guardrails applied after prompt assembly (before LiteLLM call)
rather than at the Bedrock layer. This ensures the assembled prompt (including retrieved chunks)
is filtered, not just the user query. Trade-off: adds ~50ms latency.

**Observations from deliberate exercises:**
- _[Fill in after Week 3]_ Retrieval recall at k=3/5/10: ...
- _[Fill in]_ Effect of ef_search tuning on recall vs latency: ...

---

### Gateway API

**HTTPRoute traffic splitting:** 90/10 weight split between two RAG API versions is 5 lines of
YAML in an HTTPRoute manifest. With the old Ingress model this required Nginx annotations and
was not portable. With Gateway API it is part of the spec and controller-agnostic.

**VPC Lattice vs ALB:** VPC Lattice routes traffic at the AWS network layer before it reaches
the pod network. This means TLS termination and IAM auth happen outside the cluster, reducing
the blast radius of a compromised pod.

---

## Ingestion Pipeline (Week 4)

### Chunking strategy

**Fixed-size + overlap:** 512-token chunks with 64-token overlap. Overlap ensures sentences
that span chunk boundaries are represented in both adjacent chunks, improving retrieval for
queries that match content near chunk edges. Trade-off: ~12.5% storage overhead.

**Batch embedding:** Titan Embeddings V2 supports batch inference (up to 25 inputs). Batching
20 chunks per API call reduces Bedrock API calls by 20× vs single-chunk calls, significantly
improving ingestion throughput and reducing cost.

**Observations from deliberate exercises:**
- _[Fill in after Week 4]_ Throughput at 1,000 documents: X docs/min, Y chunks/min
- _[Fill in]_ Bottleneck identified: embedding calls / pgvector writes / S3 reads
- _[Fill in]_ Tuning applied and result: ...

---

## Observability (Week 4)

### Four golden signals mapping

| Signal | Metric | Source |
|---|---|---|
| Latency | `rag_api_request_duration_seconds` (histogram) | RAG API `/metrics` |
| Traffic | `rag_api_requests_total` (counter) | RAG API `/metrics` |
| Errors | `rag_api_requests_total{status="5xx"}` | RAG API `/metrics` |
| Saturation | `vllm:num_requests_waiting` | vLLM `/metrics` |

### OTEL Collector distribution

**Decision: AWS Distro for OpenTelemetry (ADOT)**, deployed as an EKS managed add-on via
`terraform/addons/`. CloudWatch X-Ray is the sole trace destination — no Grafana Tempo.

Alternatives considered:
- `otel-collector-contrib` (upstream): full feature set, but we manage the Helm chart and
  upgrades. No benefit here — nothing in the stack needs a receiver or processor ADOT excludes.
- Grafana Alloy: would unify metrics scraping and tracing in one agent, but introduces
  Grafana-vendor coupling and more config surface for no meaningful gain.

ADOT fits the existing pattern: AWS manages the add-on lifecycle, X-Ray export works without
custom exporter config, and Pod Identity association is identical to every other workload role.
Grafana stays metrics-only (Prometheus as source). Keeping traces and metrics on separate
backends avoids coupling their retention and scaling characteristics.

**Trace propagation:** W3C TraceContext (`traceparent` header) propagated from Gateway →
RAG API → LiteLLM → Bedrock (where supported). ADOT Collector receives spans via OTLP and
exports to CloudWatch X-Ray. A single RAG request produces spans for: embedding call,
pgvector query, guardrails call, LiteLLM call, and total end-to-end.

---

## Cost observations

- _[Fill in after Week 4]_ Actual vs estimated costs at baseline load: ...
- _[Fill in]_ Most effective cost lever identified: ...
