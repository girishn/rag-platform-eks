# Build Plan

Step checklist — tick each box as the step completes. See `decisions.md` for per-component
reasoning and `docs/adr/` for the architectural decisions behind each choice.

---

## Bootstrap (once only)

- [x] Write all six ADRs in `docs/adr/` before writing any Terraform
- [x] Populate `docs/architecture/` with all eight Mermaid diagrams
- [x] Write all four runbooks in `docs/runbooks/`
- [ ] `terraform/bootstrap/` — S3 state bucket + DynamoDB lock table
- [ ] Verify state backend accessible before proceeding to Week 1

---

## Week 1 — Infrastructure Foundation

### EKS Cluster
- [ ] `terraform/eks/` — VPC (3 AZ, public + private subnets)
- [ ] `terraform/eks/` — EKS 1.35 cluster with managed node group for system pods
- [ ] `terraform/eks/` — Karpenter: CPU NodePool (AL2023, m5 family, spot+OD)
- [ ] `terraform/eks/` — Karpenter: GPU NodePool (Bottlerocket Accelerated, g5 family, spot+OD)
- [ ] Deliberately exercise: deploy GPU pod → watch Karpenter provision → delete pod → watch consolidation
- [ ] Deliberately exercise: misconfigure NodePool amiFamily → read Karpenter error logs → fix

### RDS
- [ ] `terraform/rds/` — RDS PostgreSQL 16 + pgvector extension
- [ ] `terraform/rds/` — Parameter group with `shared_preload_libraries = 'pg_vector'`
- [ ] `terraform/rds/` — Multi-AZ, private subnet group, security group from EKS only
- [ ] Create tenant schemas + HNSW index after cluster is up

### IAM (Pod Identity)
- [ ] `terraform/iam/` — Pod Identity role: rag-api (Bedrock, S3, RDS IAM auth, SSM)
- [ ] `terraform/iam/` — Pod Identity role: ingestion (Bedrock, S3, RDS IAM auth)
- [ ] `terraform/iam/` — Pod Identity role: vllm (S3 read for model weights)
- [ ] Deliberately exercise: exec into pod → `aws sts get-caller-identity` → verify role ARN
- [ ] Deliberately exercise: delete association → verify exact SDK error message

### Add-ons
- [ ] `terraform/addons/` — AWS Gateway API Controller (VPC Lattice)
- [ ] `terraform/addons/` — kube-prometheus-stack (Prometheus + Grafana + AlertManager)
- [ ] `terraform/addons/` — KEDA
- [ ] `terraform/addons/` — metrics-server
- [ ] `terraform/addons/` — EKS Pod Identity agent DaemonSet

---

## Week 2 — LLM Serving Layer

### vLLM
- [ ] `helm/vllm/` — Deployment with GPU tolerations and node selectors
- [ ] `helm/vllm/` — Init container: S3 model weight download
- [ ] `helm/vllm/` — PVC for model weight caching
- [ ] `helm/vllm/` — Service exposing port 8000
- [ ] `k8s/keda/` — ScaledObject targeting `vllm:num_requests_waiting`
- [ ] Deliberately exercise: send long-context request → vLLM OOM → pod restart → write runbook entry
- [ ] Benchmark: vLLM direct vs via LiteLLM → document P50/P95/P99 in `decisions.md`

### LiteLLM
- [ ] `helm/litellm/` — Deployment + ConfigMap-mounted `config.yaml`
- [ ] `helm/litellm/` — Bedrock primary model group (Claude 3.5 Sonnet)
- [ ] `helm/litellm/` — vLLM fallback model group
- [ ] `helm/litellm/` — Virtual key bootstrap script (per-tenant keys with budget)
- [ ] Deliberately exercise: exhaust virtual key budget → verify 429 → confirm vLLM NOT triggered
- [ ] Benchmark: LiteLLM → Bedrock vs LiteLLM → vLLM → document overhead in `decisions.md`

---

## Week 3 — RAG API and Gateway Wiring

### RAG API
- [ ] `src/rag_api/` — FastAPI app scaffold with health endpoint
- [ ] `src/rag_api/services/embedding.py` — Titan Embeddings V2 client
- [ ] `src/rag_api/services/retrieval.py` — pgvector HNSW ANN search
- [ ] `src/rag_api/services/llm_client.py` — LiteLLM passthrough with streaming
- [ ] `src/rag_api/services/guardrails.py` — Bedrock Guardrails apply/check
- [ ] `src/rag_api/routers/chat.py` — POST /v1/chat/completions (query rewrite → retrieve → assemble → stream)
- [ ] `src/rag_api/tests/` — pytest with moto for AWS + asyncpg mock
- [ ] `helm/rag-api/` — Helm chart with Pod Identity service account

### Gateway
- [ ] `k8s/gateway/` — GatewayClass (amazon-vpc-lattice)
- [ ] `k8s/gateway/` — Gateway resource
- [ ] `k8s/gateway/` — HTTPRoute → rag-api service
- [ ] `k8s/gateway/` — AuthPolicy (IAM-based tenant auth)
- [ ] Deliberately exercise: traffic weight split 90/10 → verify in Prometheus
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
- [ ] `dashboards/` — Grafana: latency P50/P95/P99 per endpoint
- [ ] `dashboards/` — Grafana: GPU utilisation + KV cache usage
- [ ] `dashboards/` — Grafana: Bedrock vs vLLM routing split
- [ ] `dashboards/` — Grafana: per-tenant token spend (from LiteLLM /spend/logs)
- [ ] `dashboards/` — Grafana: four golden signals panel
- [ ] AlertManager rules: `num_requests_waiting > 10`, `gpu_cache > 90%`, `fallback_triggered`, `error_rate > 1%`
- [ ] Deliberately exercise: artificial embedding latency → verify in trace → write Prometheus alert

### Hardening
- [ ] PodDisruptionBudgets for RAG API, LiteLLM (minAvailable: 1)
- [ ] HPA on RAG API (CPU + custom metric)
- [ ] HPA on LiteLLM
- [ ] Karpenter consolidation policy tuning
- [ ] Deliberately exercise: delete node with running pods → observe with and without PDB

### Final documentation
- [ ] `docs/cost-model.md` — complete baseline estimate + optimisation levers
- [ ] All runbooks reviewed and linked from README
- [ ] `README.md` final pass — honest status table, portfolio-ready
- [ ] GitHub: branch protection on `main`, issue templates, semantic version tag
