## Cluster State — last updated 2026-05-11
Status: RUNNING
Last provisioned: 2026-05-11
Bootstrap: intact (S3 state bucket + DynamoDB lock table — never destroyed)

## What is running
- EKS cluster: rag-platform-cluster (1.35, ap-southeast-2)
- RDS: PostgreSQL 16 + pgvector + litellm DB (Prisma schema applied)
- ElastiCache: Serverless Redis (TLS)
- IAM: Pod Identity roles — rag-api, litellm, ingestion, vllm
- S3: rag-platform-models bucket
- Addons: AWS Gateway API Controller, kube-prometheus-stack, ADOT, KEDA, metrics-server, Pod Identity agent
- vLLM Helm release: 0 replicas (KEDA-owned, no GPU provisioned until queue depth >= threshold)
- LiteLLM Helm release: 1/1 Running (litellm-migrations Job: Completed)

## PROXY_MASTER_KEY
Stored in k8s Secret `litellm-env` (rag-platform namespace). Generated on first provision.
Retrieve with: kubectl get secret litellm-env -n rag-platform -o jsonpath='{.data.PROXY_MASTER_KEY}' | base64 -d

## Pending Week 2 exercises
- Deliberately exercise: exec into pod → aws sts get-caller-identity → verify role ARN
- Deliberately exercise: delete Pod Identity association → verify exact SDK error message
- Deliberately exercise: send long-context request → vLLM OOM → pod restart → write runbook entry
- Bootstrap virtual keys: per-tenant keys with budget (build-plan.md item)
- Deliberately exercise: exhaust virtual key budget → verify 429 → confirm vLLM NOT triggered
- Benchmark: vLLM direct vs via LiteLLM → document P50/P95/P99 in decisions.md

## Next destroy
Run: uv run scripts/destroy.py --env dev
