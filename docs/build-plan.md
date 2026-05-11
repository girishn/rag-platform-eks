# Build Plan

Step checklist — tick each box as the step completes. See `decisions.md` for per-component
reasoning and `docs/adr/` for the architectural decisions behind each choice.

---

## Bootstrap (once only)

- [x] Write all eight ADRs in `docs/adr/` before writing any Terraform
- [x] Populate `docs/architecture/` with all eight Mermaid diagrams
- [x] Write all four runbooks in `docs/runbooks/`
- [x] `terraform/bootstrap/` — S3 state bucket + DynamoDB lock table
- [x] Verify state backend accessible before proceeding to Week 1

---

## Week 1 — Infrastructure Foundation

### EKS Cluster
- [x] `terraform/eks/` — VPC (3 AZ, public + private subnets)
- [x] `terraform/eks/` — EKS 1.35 cluster with managed node group for system pods
- [x] `terraform/eks/` — Karpenter: CPU NodePool (AL2023, m5 family, spot+OD)
- [x] `terraform/eks/` — Karpenter: GPU NodePool (Bottlerocket Accelerated, g5 family, spot+OD)
- [ ] Deliberately exercise: deploy GPU pod → watch Karpenter provision → delete pod → watch consolidation
- [ ] Deliberately exercise: misconfigure NodePool amiFamily → read Karpenter error logs → fix

### RDS
- [x] `terraform/rds/` — RDS PostgreSQL 16 + pgvector extension (single-AZ for dev)
- [x] `terraform/rds/` — Custom parameter group (pgvector needs no shared_preload_libraries on RDS — installs via CREATE EXTENSION)
- [x] `terraform/rds/` — Private subnet group, security group from EKS VPC CIDR only
- [x] `terraform/rds/` — Create `litellm` database on same RDS instance (automated in provision.py post-rds step)
- [ ] Create tenant schemas + HNSW index after cluster is up

### ElastiCache
- [x] `terraform/elasticache/` — ElastiCache Serverless for Redis (TLS, network-layer auth only)
- [x] `terraform/elasticache/` — Security group: allow inbound 6379 from VPC CIDR only
- [x] `terraform/elasticache/` — outputs.tf exposing rediss:// endpoint for LiteLLM Helm values

### IAM (Pod Identity)
- [x] `terraform/iam/` — Pod Identity role: rag-api (Bedrock, S3, `rds-db:connect` IAM auth)
- [x] `terraform/iam/` — Pod Identity role: litellm (`secretsmanager:GetSecretValue` for DATABASE_URL only — password auth, not RDS IAM)
- [x] `terraform/iam/` — Pod Identity role: ingestion (Bedrock, S3, `rds-db:connect` IAM auth, Textract)
- [x] `terraform/iam/` — Pod Identity role: vllm (S3 read for model weights)
- [x] Deliberately exercise: exec into pod → `aws sts get-caller-identity` → verify role ARN
- [x] Deliberately exercise: delete association → verify exact SDK error message

### Add-ons
- [x] `terraform/addons/` — AWS Gateway API Controller (VPC Lattice)
- [x] `terraform/addons/` — kube-prometheus-stack (Prometheus + Grafana + AlertManager)
- [x] `terraform/addons/` — AWS Distro for OpenTelemetry (ADOT) EKS managed add-on
- [x] `terraform/addons/` — KEDA
- [x] `terraform/addons/` — metrics-server
- [x] `terraform/eks/` — EKS Pod Identity agent (moved from addons — must precede any Pod Identity association)

---

## Week 2 — LLM Serving Layer

### vLLM
- [x] `helm/vllm/` — Deployment with GPU tolerations and node selectors
- [x] `helm/vllm/` — Init container: S3 model weight download
- [x] `helm/vllm/` — PVC for model weight caching
- [x] `helm/vllm/` — Service exposing port 8000
- [x] `k8s/keda/` — ScaledObject targeting `vllm:num_requests_waiting`
- [ ] Deliberately exercise: send long-context request → vLLM OOM → pod restart → write runbook entry
- [ ] Benchmark: vLLM direct vs via LiteLLM → document P50/P95/P99 in `decisions.md`

### LiteLLM
- [x] `helm/litellm/` — Deployment + ConfigMap-mounted `config.yaml`
- [x] `helm/litellm/` — `DATABASE_URL` from Secrets Manager CSI driver → k8s Secret sync
- [x] `helm/litellm/` — `REDIS_URL` as env var (ElastiCache Serverless endpoint, `rediss://` scheme, no password — network-layer auth only)
- [x] `helm/litellm/` — Bedrock primary model group (Claude 3.5 Sonnet)
- [x] `helm/litellm/` — vLLM fallback model group
- [x] `helm/litellm/` — Virtual key bootstrap script (per-tenant keys with budget)
- [x] Deliberately exercise: exhaust virtual key budget → verify 400 → confirm vLLM NOT triggered
- [ ] Benchmark: LiteLLM → Bedrock vs LiteLLM → vLLM → document overhead in `decisions.md`

---

## Week 3 — RAG API and Gateway Wiring

### RAG API
- [ ] `src/rag_api/` — FastAPI app scaffold with health endpoint
- [ ] `src/rag_api/services/embedding.py` — Titan Embeddings V2 client
- [ ] `src/rag_api/services/tenant.py` — LiteLLM `/key/info` lookup + TTLCache (60s), maps virtual key → tenant_id → schema
- [ ] `src/rag_api/services/retrieval.py` — pgvector HNSW ANN search (pool-per-tenant, `search_path` via `server_settings`)
- [ ] `src/rag_api/services/llm_client.py` — LiteLLM passthrough with streaming
- [ ] `src/rag_api/services/guardrails.py` — pass-through stub (phase 2: wire Bedrock Guardrails)
- [ ] `src/rag_api/routers/chat.py` — POST /v1/chat/completions (retrieve → assemble → stream)
- [ ] `src/rag_api/tests/` — pytest with moto for AWS + asyncpg mock
- [ ] `helm/rag-api/` — Helm chart with Pod Identity service account

### Gateway
- [ ] `k8s/gateway/` — GatewayClass (amazon-vpc-lattice)
- [ ] `k8s/gateway/` — Gateway resource
- [ ] `k8s/gateway/` — HTTPRoute → Grafana (admin access via VPC Lattice, non-streaming)
- [ ] `k8s/gateway/` — AuthPolicy (IAM-based auth on admin routes)
- [ ] `k8s/gateway/` — TargetGroupBinding for RAG API (ALB → pod direct, SSE streaming path)
- [ ] `terraform/eks/` or `helm/rag-api/` — ALB `idle_timeout = 300` (LLM streaming headroom)
- [ ] Deliberately exercise: ALB weighted target groups 90/10 split → verify routing in Prometheus
- [ ] Deliberately exercise: wrong vector_dims → observe error → understand migration path

---

## Week 4 — Ingestion, Observability, Hardening

### Ingestion Pipeline
- [ ] `src/ingestion/` — S3 reader + document chunker (fixed-size + overlap)
- [ ] `src/ingestion/` — Titan Embeddings batch caller (20 chunks per call)
- [ ] `src/ingestion/` — pgvector upsert with ETag deduplication
- [ ] `helm/ingestion/` — CronJob Helm chart
- [ ] Run against 1,000 documents → measure throughput → identify bottleneck → document in `decisions.md`

### Observability
- [ ] Configure ADOT Collector: OTLP receiver + AWS X-Ray exporter (instrument RAG API and LiteLLM with OTEL SDK)
- [ ] `dashboards/` — Grafana: latency P50/P95/P99 per endpoint
- [ ] `dashboards/` — Grafana: GPU utilisation + KV cache usage
- [ ] `dashboards/` — Grafana: Bedrock vs vLLM routing split
- [ ] `dashboards/` — Grafana: four golden signals panel
- [ ] AlertManager rules: `num_requests_waiting > 10`, `gpu_cache > 90%`, `fallback_triggered`, `error_rate > 1%`
- [ ] Deliberately exercise: artificial embedding latency → verify in X-Ray trace → write Prometheus alert

### Hardening
- [ ] PodDisruptionBudgets for RAG API, LiteLLM (minAvailable: 1)
- [ ] Karpenter consolidation policy tuning
- [ ] Deliberately exercise: delete node with running pods → observe with and without PDB

### Final documentation
- [ ] `docs/cost-model.md` — complete baseline estimate + optimisation levers
- [ ] All runbooks reviewed and linked from README
- [ ] `README.md` final pass — honest status table, portfolio-ready
- [ ] GitHub: branch protection on `main`, issue templates, semantic version tag

---

## Phase 2 — Post-MVP Enhancements

Deferred after initial build. Document the pattern in `decisions.md`; implement when phase 1
is stable and deployed.

| Feature | Notes |
|---|---|
| Source references / citations | Return `doc_id` + similarity score from retrieval; label context blocks with source name; instruct LLM to inline-cite using `[N]` notation; append a guaranteed `Sources:` block at end of stream. Two file changes: `retrieval.py` SELECT + `chat.py` prompt assembly. No infrastructure changes. |
| Multi-turn chat context | Client sends full `messages` array; server uses last-N turns for contextualized retrieval query. See `decisions.md`. |
| Query rewriting | Haiku call to rewrite user query before embedding. Improves recall on ambiguous queries. Service slot exists in `src/rag_api/routers/chat.py`. |
| Bedrock Guardrails | Stub exists at `src/rag_api/services/guardrails.py`. Wire Bedrock Guardrails resource + apply/check calls. Adds ~50ms latency. |
| Per-tenant cost dashboards | LiteLLM `/spend/logs` → Grafana per-tenant spend breakdown. Overall cost dashboard ships in phase 1. |
| HPA on RAG API + LiteLLM | CPU-based horizontal scaling. KEDA scale-to-zero on vLLM (GPU cost) ships in phase 1. |
| Client VPN admin path | IAM Identity Center + AWS Client VPN for admin access to internal services. Phase 1 uses `kubectl port-forward` for Grafana access. |
| Agentic RAG | Iterative retrieval (LLM decides if context is sufficient), sub-question decomposition, tool use beyond vector search. Builds on multi-turn chat. No infrastructure changes needed — change is in `routers/chat.py` only. |
