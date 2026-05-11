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

**Bedrock model selection — inference profiles required for Claude 4.x:**
Direct foundation model IDs (e.g. `anthropic.claude-sonnet-4-5-20250929-v1:0`) fail with
"on-demand throughput isn't supported" for Claude 4.x. These models require a cross-region
inference profile ID instead (e.g. `au.anthropic.claude-sonnet-4-5-20250929-v1:0` for
ap-southeast-2). The `au.` profile routes to `ap-southeast-4` (Melbourne) at Bedrock's
discretion, so the IAM `bedrock:InvokeModel` resource must use `arn:aws:bedrock:*::foundation-model/*`
(wildcard region) rather than the home region. Use `aws bedrock list-inference-profiles --region`
to discover available profiles; `au.` = Australia, `apac.` = broader Asia Pacific.

Claude 3.x models (e.g. `claude-3-5-sonnet-20241022-v2:0`) eventually go Legacy if not used
for 30+ days. Use active 4.x inference profiles for all new deployments.

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

**LiteLLM → RDS auth: password from Secrets Manager (not RDS IAM auth).**
RDS IAM auth generates a 15-minute token used as the PostgreSQL password. asyncpg (used by
rag-api and ingestion) can generate a fresh token per connection attempt, so RDS IAM auth works
cleanly there. Prisma holds a persistent connection pool and has no native token-refresh hook —
forcing IAM auth would require a sidecar or custom connection factory. Instead: a dedicated
`litellm` PostgreSQL user, password stored in Secrets Manager, rotated by Secrets Manager
automatic rotation. LiteLLM reads `DATABASE_URL` at pod startup via the Secrets Manager CSI
driver. The litellm Pod Identity role needs `secretsmanager:GetSecretValue` only — no
`rds-db:connect`.

Redis is non-negotiable for performance. Without it, every LLM request makes a synchronous
PostgreSQL query to validate the virtual key and check the tenant's budget. With Redis, key
metadata is cached after first hit (~0.5ms GET vs ~3ms RDS query). LiteLLM also increments
spend atomically in Redis (INCRBYFLOAT) and flushes to PostgreSQL in batches — this eliminates
a DB write on every token-counting event.

**Why ElastiCache Serverless over in-cluster Redis pod:**
An in-cluster pod has no persistence guarantees — a pod restart wipes the key cache and forces
cold RDS lookups until it warms up. ElastiCache Serverless is managed, multi-AZ by default,
and requires no capacity planning.

**ElastiCache auth: network-layer security only (no Redis AUTH password).**
ElastiCache IAM token auth requires rotating a short-lived STS token every 15 minutes as the
Redis `AUTH` password — LiteLLM has no native support for this refresh cycle. Instead, access
is controlled purely at the network layer: TLS in transit (`rediss://` scheme) and a security
group that allows inbound 6379 exclusively from the LiteLLM pod CIDR. No password in config,
no Secrets Manager entry for Redis. The Pod Identity IAM auth story is reserved for services
where the SDK genuinely supports it end-to-end (Bedrock, S3, RDS).

**Budget vs backend error distinction:** This is the most important operational concept.
A virtual key budget exhaustion returns **HTTP 400** (`type: "budget_exceeded"`) from LiteLLM
and does NOT trigger the fallback chain — the tenant has spent their allowance. A Bedrock
ThrottlingException is a backend 5xx error that SHOULD trigger fallback. LiteLLM's
retry/fallback config handles this distinction correctly by design; the key is understanding it
when reading logs.

Note: early docs assumed budget exhaustion returns 429 — the actual status is 400 in
LiteLLM v1.82.3. The operational implication is the same (client must handle 400 for budget).

**Observations from deliberate exercises:**
- Budget exhausted response body (LiteLLM v1.82.3):
  `{"error": {"message": "Budget has been exceeded! Current cost: 0.0, Max budget: 0.0", "type": "budget_exceeded", "param": null, "code": "400"}}`
- vLLM replicas after budget-exhausted request: 0 — fallback chain confirmed NOT triggered
- _[Fill in]_ LiteLLM log line when fallback triggers: `...`

---

## RAG API (Week 3)

### Tenant resolution

**RAG API resolves tenant via LiteLLM `/key/info` + in-process LRU cache.**

Client sends `Authorization: Bearer <virtual-key>`. RAG API calls LiteLLM `GET /key/info`
with that token before touching pgvector. LiteLLM returns key metadata including a `tenant_id`
field set at key creation time. RAG API maps `tenant_id → schema_name` (`tenant_{id}`) and
sets `search_path` at the asyncpg connection string level (not in application code — per
ADR-007 risk note).

LRU cache (in-process, `cachetools.TTLCache`, TTL=60s) avoids a round-trip on every request
after first hit. Cache keyed on the raw virtual key string. On 401/403 from LiteLLM, evict
and return 401 to the client — do not fall through to pgvector with a stale tenant.

`X-Tenant-ID` header from the client is explicitly rejected — tenant identity must come from
the authenticated virtual key, not a client-supplied claim.

**pgvector connection pools: one pool per tenant.**
ADR-007 warns that a shared pool with `SET search_path` on borrow risks schema leakage if the
reset is missed. Safest model at portfolio scale (<10 tenants): one `asyncpg.Pool` per tenant,
`min_size=1, max_size=3`, `search_path` set via `server_settings` at pool creation. No per-request
`SET` call needed — the connection is always in the correct schema. Pool is created lazily on
first request for that tenant and cached for the pod lifetime. If tenant count grows past ~20,
revisit with a single pool + explicit reset-on-release (`try/finally`).

### Query pipeline design

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
