# Cost Model

Estimated monthly AWS cost at baseline load, with optimisation levers and their projected
savings. Baseline assumption: **100 RAG queries/day, 1,000 documents ingested/month**,
single-tenant, `ap-southeast-2` region, May 2026 pricing.

---

## Baseline cost table

| Component | Service | Config | Est. monthly cost |
|---|---|---|---|
| EKS control plane | EKS | 1 cluster | $73 |
| CPU nodes (system + app) | EC2 (spot m5.xlarge) | 2 nodes avg, 730hr | ~$110 |
| GPU node (vLLM) | EC2 (spot g5.xlarge) | scale-to-zero, ~4hr/day | ~$30 |
| RDS PostgreSQL | RDS (db.t4g.medium, Multi-AZ) | 1 instance, 100GB storage | ~$80 |
| Bedrock — LLM | Bedrock (Claude 3.5 Sonnet) | 100 req/day × 2K tokens avg | ~$15 |
| Bedrock — Embeddings | Bedrock (Titan Embeddings V2) | 100 queries + 1K doc chunks | ~$1 |
| S3 | S3 Standard | 10GB docs + model weights | ~$3 |
| VPC Lattice | VPC Lattice | 100 req/day, minimal LCU | ~$2 |
| NAT Gateway | NAT Gateway | 2 AZ, 10GB/month | ~$35 |
| CloudWatch | CloudWatch | Logs + metrics + X-Ray | ~$10 |
| ECR | ECR | 3 repos, ~5GB images | ~$1 |
| **Total** | | | **~$360/month** |

> Note: GPU node cost assumes KEDA scale-to-zero during off-peak hours. Without scale-to-zero,
> a single g5.xlarge on-demand runs 24/7 at ~$350/month — scale-to-zero is the single biggest
> GPU cost lever.

---

## Optimisation levers

| Lever | Action | Est. saving | Notes |
|---|---|---|---|
| GPU scale-to-zero | KEDA minReplicas=0 off-peak; Karpenter consolidates idle GPU node | $280–$320/month | Primary cost lever. Tradeoff: 3–5 min cold start for first request after scale-from-zero. Mitigate with minReplicas=1 during business hours. |
| Spot instances (CPU) | Karpenter spot-first for CPU NodePool | $40–$60/month | Already included in baseline. Interruption risk mitigated by multi-AZ + >1 replica. |
| Spot instances (GPU) | Karpenter spot-first for GPU NodePool with on-demand fallback | $80–$120/month | Already included in baseline. g5 spot discount is typically 60–70%. |
| RDS rightsizing | db.t4g.small instead of t4g.medium at low query volume | ~$25/month | Evaluate after 1 month of baseline metrics. pgvector is memory-sensitive; don't over-optimise. |
| Bedrock Provisioned Throughput | PTUs instead of on-demand for >50K tokens/day per model | 30–40% token cost reduction | Not cost-effective at baseline (100 req/day). Re-evaluate at 1,000 req/day. |
| NAT Gateway → VPC Endpoints | S3 VPC Endpoint eliminates S3 traffic NAT charges | ~$10–$15/month | Worth doing: S3 Gateway endpoint is free; removes S3 traffic from NAT meter. |
| Single-AZ RDS (non-prod) | Disable Multi-AZ in dev/staging | ~$35/month | Acceptable for non-production. Never disable in prod — RDS Multi-AZ is the HA mechanism. |

---

## Cost at scale

| Scale | Queries/day | Est. monthly cost | Primary driver |
|---|---|---|---|
| Baseline | 100 | ~$360 | EKS + RDS fixed costs |
| 10× | 1,000 | ~$550 | Bedrock tokens + larger CPU nodes |
| 100× | 10,000 | ~$1,500 | Bedrock tokens; consider Provisioned Throughput |
| 1,000× | 100,000 | ~$8,000 | Bedrock PTUs + more GPU replicas + RDS read replica |

> At 100K queries/day, Bedrock on-demand tokens cost ~$5,000/month alone. Provisioned Throughput
> units break even at roughly this scale depending on average token count per request.

---

## Cost monitoring setup

- CloudWatch billing alert: notify at $200/month (half of baseline)
- Per-tenant cost: LiteLLM `/spend/logs` API → Grafana dashboard
- GPU cost visibility: tag GPU EC2 instances with `component=vllm` → Cost Explorer filter
- Spot interruption preparedness: Karpenter events in CloudWatch → alert on `SpotInterruptionWarning`
