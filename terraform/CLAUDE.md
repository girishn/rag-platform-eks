# Terraform Conventions

## State backend
S3 + DynamoDB lock in `terraform/bootstrap/`. Bootstrap run once only — never touched by `provision.py`/`destroy.py`.

## Pod Identity pattern
```hcl
module "rag_api_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "2.5.0"

  name                    = "${var.name_prefix}-rag-api"
  attach_custom_policy    = true
  source_policy_documents = [data.aws_iam_policy_document.rag_api.json]

  associations = {
    rag-api = {
      cluster_name    = module.eks.cluster_name
      namespace       = "rag-platform"
      service_account = "rag-api"
    }
  }

  tags = var.tags
}
```
No OIDC provider setup. No SA annotation. Association via EKS API only.

## Module layout
Every module must have `variables.tf`, `outputs.tf`, `main.tf`. All resources tagged with `var.tags`.

## Add-on version pinning
Pin EKS add-on versions explicitly — never `most_recent = true` in prod. VPC CNI + EBS CSI use IRSA (no Pod Identity support yet).
