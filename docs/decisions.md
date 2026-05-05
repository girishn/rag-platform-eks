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

### LiteLLM key storage

**Decision: existing RDS instance (`litellm` DB) + ElastiCache Serverless for Redis.**

LiteLLM uses Prisma to manage its own schema — it just needs a `DATABASE_URL` pointing at a
PostgreSQL database. A separate `litellm` database on the same RDS instance keeps storage costs
flat and avoids a second RDS cluster. The pgvector and LiteLLM workloads are distinct enough
(HNSW vector queries vs OLTP key lookups) that they won't contend at portfolio-project load.

Redis is non-negotiable for performance. Without it, every LLM request makes a synchronous
PostgreSQL query to validate the virtual key and check the tenant's budget. With Redis, key
metadata is cached after first hit (~0.5ms GET vs ~3ms RDS query). LiteLLM also increments
spend atomically in Redis (INCRBYFLOAT) and flushes to PostgreSQL in batches — this eliminates
a DB write on every token-counting event.

**Why ElastiCache Serverless over in-cluster Redis pod:**
An in-cluster pod has no persistence guarantees — a pod restart wipes the key cache and forces
cold RDS lookups until it warms up. More importantly, the project constraint is no static
credentials; ElastiCache Serverless supports IAM authentication, so LiteLLM pods connect via
a short-lived IAM token obtained through Pod Identity, with no password in config.

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

### Phase 2: Agentic RAG

The phase 1 pipeline is deliberately linear: one retrieval pass, fixed prompt assembly, LLM
as a pure generator. It handles factual single-step queries well but fails on questions that
require multiple retrieval steps or external actions — e.g. "compare Q3 results across all
tenant reports and calculate the aggregate."

**Why the current design is the right foundation for adding this later:**
LiteLLM already supports tool/function calling (passed through to Bedrock Claude and vLLM
Llama if the model supports it). pgvector retrieval is already a callable service. The only
change needed is in `routers/chat.py` — replacing the linear pipeline with a loop that lets
the model decide when to retrieve, what to retrieve, and when it has enough context to answer.

**Planned patterns (phase 2, in order of complexity):**

1. **Iterative retrieval (corrective RAG):** after the first retrieval, ask the LLM to assess
   whether the context is sufficient. If not, it reformulates the query and retrieves again.
   Caps at N rounds to prevent infinite loops.

2. **Sub-question decomposition:** for multi-part questions, decompose into sub-queries via an
   LLM call, retrieve independently for each, then pass all context to the final synthesis call.
   Pairs naturally with multi-turn chat (also phase 2).

3. **Tool use beyond retrieval:** define tools as LiteLLM function schemas — e.g. a SQL
   aggregation tool, a calculator, an external API. The LLM decides which tool to call based
   on the query. This is what Bedrock Agents provides as a managed service; here it's
   implemented in application code, which gives full observability and no service limits.

---

### Gateway API

**Routing split — ALB for external, VPC Lattice for internal/admin only:**
VPC Lattice has a hard 1-minute idle connection timeout and ambiguous streaming behaviour —
it is unsuitable for SSE responses from an LLM backend where a slow context or queued request
can stall token delivery. The external path is therefore ALB → RAG API pod directly via
`TargetGroupBinding` (AWS Load Balancer Controller). ALB idle timeout is set to 300s in
Terraform, giving enough headroom for long completions.

VPC Lattice remains for admin routing (Grafana HTTPRoute) and internal service policy
enforcement. IAM AuthPolicy at the route level still applies to those non-streaming paths.

**Traffic splitting for canary deployments:** Since VPC Lattice is not in the external path,
canary splits for the RAG API use ALB weighted target groups (two `TargetGroupBinding` objects
with weights set on the ALB listener rule). HTTPRoute weight splits still apply to the
VPC Lattice-managed internal routes.

**VPC Lattice vs ALB:** VPC Lattice routes traffic at the AWS network layer before it reaches
the pod network, which means IAM AuthPolicy applies before any pod code runs. This benefit is
preserved for admin routes. It is intentionally not used on the hot streaming path.

---

## Ingestion Pipeline (Week 4)

### Document parsing strategy

**Two-tier approach: `unstructured` library + Amazon Textract.**

`unstructured` handles all native-digital formats (PDF with text layer, DOCX, PPTX, XLSX, HTML,
Markdown, CSV, RTF) via a single `partition()` call. It auto-detects the format from the file
extension hint passed via `metadata_filename` and returns semantically meaningful elements
(paragraphs, tables, list items) rather than raw bytes — better chunking input than a flat
byte stream.

Textract handles two cases:
- **Image files** (JPEG, PNG, TIFF): synchronous `detect_document_text` call, result returned inline.
- **Scanned PDFs**: detected when `unstructured` returns fewer than 200 chars from a `.pdf`
  (indicating no text layer). Falls back to `start_document_text_detection` (async, S3 source),
  polling every 5 seconds until the job completes. The document is already in S3 so no re-upload
  is needed — Textract reads it directly via the S3 key.

Why not Textract for everything: Textract charges per page ($0.0015/page for native PDF,
$0.065/page with OCR). `unstructured` is free for native-digital documents. The fallback-only
pattern minimises Textract cost to genuinely scanned content.

The IAM role for the ingestion pod requires `textract:DetectDocumentText`,
`textract:StartDocumentTextDetection`, and `textract:GetDocumentTextDetection`.

Unsupported formats (e.g. `.mp4`, `.zip`) log a warning and are skipped — the pipeline
continues to the next document rather than crashing.

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

### Structured logging with trace ID correlation

X-Ray traces show latency breakdown and error location per request, but not the application
detail behind a failed span (which chunks were retrieved, what error the service threw, etc.).
To bridge traces and logs, every log line emitted while an OTEL span is active includes
`trace_id` and `span_id` as structured JSON fields.

In CloudWatch Logs Insights, a slow or failed X-Ray trace can be drilled into immediately:
```
fields @message | filter trace_id = "1-abc123..."
```

Implementation: `src/rag_api/logging_config.py` — a `logging.Formatter` subclass that calls
`opentelemetry.trace.get_current_span().get_span_context()` on each record. Because
`FastAPIInstrumentor` creates a span per HTTP request before any handler code runs, every log
line inside a request handler automatically carries the correct trace/span context.

The `trace_id` in logs is raw 32-char hex. The ADOT Collector converts OTEL trace IDs to
X-Ray format (`1-{8hex}-{24hex}`) when exporting — so the CloudWatch Logs trace_id value
matches what X-Ray displays after stripping the `1-` prefix and dash.

### Four golden signals mapping

| Signal | Metric | Source |
|---|---|---|
| Latency | `rag_api_request_duration_seconds` (histogram) | RAG API `/metrics` |
| Traffic | `rag_api_requests_total` (counter) | RAG API `/metrics` |
| Errors | `rag_api_requests_total{status="5xx"}` | RAG API `/metrics` |
| Saturation | `vllm:num_requests_waiting` | vLLM `/metrics` |

### ADOT Collector distribution

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
