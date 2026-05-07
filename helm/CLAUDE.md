# Helm Conventions

## LiteLLM
- Bedrock = primary model group, vLLM = fallback. Config in `litellm/config.yaml` (ConfigMap-mounted).
- Virtual keys: per-tenant `max_budget` + `rpm_limit`. Spend tracked, exposed via `/spend`.
- `DATABASE_URL` from Secrets Manager CSI driver → litellm DB on RDS (password auth, not RDS IAM).
- Redis: `rediss://` scheme (TLS), no AUTH password — security group controls access.
- **Budget 429 ≠ backend error.** Budget exhaustion does NOT trigger vLLM fallback. Backend 5xx does.
- Fallback chain: Bedrock → vLLM. Both fail → 503. Never silently drop.

## vLLM
- Model weights in S3, init container pulls at pod start. No weights baked into image.
- Image: `763104351884.dkr.ecr.ap-southeast-2.amazonaws.com/vllm-inference:latest`
- GPU NodePool: g5 family (A10G), spot + on-demand fallback.
- KEDA ScaledObject targets `vllm:num_requests_waiting` — queue depth, not CPU.
- KEDA scale-to-zero enabled. `--tensor-parallel-size` via env var.

## Observability
- Prometheus scrapes: `/metrics` on RAG API, LiteLLM, vLLM + DCGM exporter for GPU.
- Alert thresholds: `num_requests_waiting > 10`, `gpu_cache_usage_perc > 90`.
- ADOT Collector: OTLP receiver → CloudWatch X-Ray exporter (managed EKS add-on).
- Grafana dashboards exported to `dashboards/` as JSON, version-controlled.
