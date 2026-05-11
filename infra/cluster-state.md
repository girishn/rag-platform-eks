## Cluster State — last updated 2026-05-11
Status: DESTROYED
Last destroyed: 2026-05-11 (exit code 0)
Bootstrap: intact (S3 state bucket + DynamoDB lock table — never destroyed)

## What was running before destroy
- EKS cluster: rag-platform-cluster (1.35, ap-southeast-2)
- RDS: PostgreSQL 16 + pgvector + litellm DB (Prisma schema applied)
- ElastiCache: Serverless Redis (TLS)
- IAM: Pod Identity roles — rag-api, litellm, ingestion, vllm
- S3: rag-platform-models bucket
- Addons: AWS Gateway API Controller, kube-prometheus-stack, ADOT, KEDA, metrics-server, Pod Identity agent
- vLLM Helm release: 0 replicas (KEDA-owned)
- LiteLLM Helm release: healthy, Bedrock Claude Sonnet 4.5 confirmed working

## Week 2 status at destroy
All Week 2 Terraform + Helm items complete. Verified working:
- LiteLLM → Bedrock (au.anthropic.claude-sonnet-4-5-20250929-v1:0): HTTP 200 confirmed
- Budget exhaustion: HTTP 400, type=budget_exceeded, vLLM fallback NOT triggered
- Pod Identity: role ARN verified from inside pod; deletion fallback behaviour documented

## Known IAM requirements for next provision
- litellm + rag-api roles need arn:aws:bedrock:*::foundation-model/* (wildcard region)
  and arn:aws:bedrock:{region}:{account}:inference-profile/* for Claude 4.x inference profiles
- Already in terraform/iam/main.tf — will apply on next provision

## Next provision
Run: uv run scripts/provision.py --env dev --skip-bootstrap
Then: uv run scripts/bootstrap_keys.py

## Week 3 starting point
- src/rag_api/ — FastAPI scaffold
- k8s/gateway/ — GatewayClass, HTTPRoute, TargetGroupBinding
