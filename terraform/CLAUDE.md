# Terraform Conventions

## State backend
S3 + DynamoDB lock in `terraform/bootstrap/`. Bootstrap run once only — never touched by `provision.py`/`destroy.py`.

## Pod Identity pattern
Use native resources — `terraform-aws-modules/eks-pod-identity/aws` v2.x requires aws >= 6.x, incompatible with `~> 5.80`.

```hcl
resource "aws_iam_role" "workload" {
  for_each           = local.workloads
  name               = "${var.name_prefix}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_trust.json
  tags               = var.tags
}

resource "aws_eks_pod_identity_association" "workload" {
  for_each        = local.workloads
  cluster_name    = local.cluster_name
  namespace       = var.app_namespace
  service_account = each.value.service_account
  role_arn        = aws_iam_role.workload[each.key].arn
  tags            = var.tags
}
```

Trust policy principal: `pods.eks.amazonaws.com`, actions: `sts:AssumeRole` + `sts:TagSession`.

## Cross-module values
Downstream modules read upstream outputs via `terraform_remote_state`. `dev.tfvars` provides `env` and `state_bucket` to all modules.

## Module layout
Every module must have `variables.tf`, `outputs.tf`, `main.tf`. All resources tagged with `var.tags`.

## Add-on version pinning
Pin EKS add-on versions explicitly. Check with:
```bash
aws eks describe-addon-versions --kubernetes-version 1.35 --addon-name <name> \
  --query 'addons[0].addonVersions[0].addonVersion' --output text
```
VPC CNI + EBS CSI use IRSA (no Pod Identity support). `eks-pod-identity-agent` belongs in the EKS cluster addons, not in `addons/` — it must exist before any Pod Identity association is used.

## pgvector
Does not require `shared_preload_libraries` on RDS. Install with `CREATE EXTENSION vector;` after connecting.

## VPC endpoints
Interface endpoints deferred to prod (ADR-009, cost $281/month in dev). S3 Gateway endpoint retained (free).
