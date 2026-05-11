# CLAUDE.md — RAG Platform on EKS

Multi-tenant RAG on EKS: Bedrock primary → vLLM fallback, pgvector schema isolation, Gateway API + VPC Lattice, full LLM observability. Portfolio-grade AI Platform Engineering reference.

## Stack
EKS 1.35 + Karpenter | LiteLLM (Bedrock → vLLM) | pgvector/RDS | FastAPI | Python 3.13 + uv | Terraform | ap-southeast-2

## Commands
```bash
uv run scripts/test.py           # full test suite
uv run scripts/lint.py           # ruff + mypy
uv run scripts/tf_validate.py    # fmt + validate + tflint
uv run scripts/provision.py --env dev [--skip-bootstrap]   # terraform apply + helm installs
uv run scripts/destroy.py --env dev [--include-bootstrap]  # full teardown
uv run scripts/benchmark.py --endpoint <url>  # load test
```

## Hard constraints
- **Auth:** Pod Identity for all app workloads. IRSA only for VPC CNI/EBS CSI. No static creds.
- **K8s:** 1.35. No deprecated APIs. No `v1beta1`. No Ingress. `HTTPRoute` only.
- **Node AMIs:** AL2023 (CPU), Bottlerocket Accelerated (GPU).
- **Python:** Type hints on all fn signatures. No bare `except`. `uv add` only.
- **Terraform:** `var.tags` on every resource. Every module: `variables.tf` + `outputs.tf`.
- **Containers:** Non-root user, multi-stage builds, push to ECR.
- **Admission webhooks:** `failurePolicy: Ignore`.

## AWS conventions
- Region: `ap-southeast-2` | Prefix: `var.name_prefix`
- Pod Identity: native `aws_iam_role` + `aws_eks_pod_identity_association` (eks-pod-identity v2.x requires aws 6.x, incompatible with ~> 5.80)
- EKS Blueprints Addons: `aws-ia/eks-blueprints-addons/aws` v1.23.0
- EKS module: `terraform-aws-modules/eks/aws` (latest)

## Working pattern
Write ADR → update `docs/decisions.md` → implement → tick `docs/build-plan.md`.
ADRs immutable once Accepted — write new ADR to supersede, never edit.

## Sub-directory guidance
- `terraform/CLAUDE.md` — IaC patterns, Pod Identity HCL, state backend
- `src/CLAUDE.md` — Python/testing conventions
- `helm/CLAUDE.md` — LiteLLM routing, vLLM, observability config
- `docs/CLAUDE.md` — ADR rules, diagram conventions, runbook template, cost model

@docs/build-plan.md
@docs/decisions.md

## Session Protocol
1. Always read `./infra/cluster-state.md` before doing anything
2. After any infra change (provision/destroy), update cluster-state.md
3. Never assume cluster is running — check state file first