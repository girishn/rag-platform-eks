# ADR-004: EKS Pod Identity over IRSA for Application Workload IAM

**Date:** 2026-05-04
**Status:** Accepted
**Deciders:** Girish Narayanan

## Context

All application workloads on EKS (RAG API, ingestion CronJob, LiteLLM proxy, vLLM) require
AWS IAM permissions to access Bedrock, S3, RDS, and SSM Parameter Store. Two mechanisms exist
for granting these permissions without static credentials: IRSA (IAM Roles for Service Accounts)
and the newer EKS Pod Identity.

## Decision

Use EKS Pod Identity (`aws_eks_pod_identity_association`) for all application workloads.
IRSA is retained only for EKS system add-ons that do not yet support Pod Identity
(VPC CNI, EBS CSI driver). No static IAM credentials anywhere in the platform.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| EKS Pod Identity | No per-cluster OIDC provider required; roles reusable across clusters; session tags enable ABAC; simpler Terraform (no `aws_iam_openid_connect_provider`); AWS-recommended path going forward | EKS 1.24+ only; requires `eks-pod-identity-agent` add-on installed on each node |
| IRSA | Mature, widely documented, works on all EKS versions | Per-cluster OIDC provider is a shared dependency; role trust policies are cluster-specific (not portable); service account annotation is manual and error-prone |
| Static IAM keys in Kubernetes Secrets | Simple to implement | Violates security baseline; key rotation is manual; Secret contents are base64-encoded in etcd (not encrypted by default); never acceptable in production |

## Consequences

**Easier:**
- IAM roles are not coupled to a specific cluster's OIDC issuer URL — the same role can be
  associated with pods across multiple clusters via the EKS API.
- ABAC patterns (e.g. restricting an S3 path by tenant ID via session tag) are possible without
  per-tenant IAM roles.
- Terraform module `terraform-aws-modules/eks-pod-identity/aws` v2.5.0 handles the association
  resource, reducing boilerplate significantly.

**Harder:**
- `eks-pod-identity-agent` DaemonSet must be healthy on every node — a crashing agent means
  pods on that node cannot assume their roles. Add an alert for DaemonSet unavailability.
- Debugging credential issues requires checking both the pod association (EKS API) and the role
  trust policy — two places instead of one.

**Risks:**
- EKS system add-ons (VPC CNI, EBS CSI) still use IRSA as of EKS 1.35. This creates a mixed
  pattern in the cluster. Document clearly which workloads use which mechanism.

## References

- [EKS Pod Identity announcement](https://aws.amazon.com/blogs/aws/amazon-eks-pod-identity-simplifies-iam-permissions-for-applications-on-amazon-eks/)
- [Pod Identity vs IRSA comparison](https://docs.aws.amazon.com/eks/latest/userguide/pod-id-how-it-works.html)
- [terraform-aws-modules/eks-pod-identity](https://registry.terraform.io/modules/terraform-aws-modules/eks-pod-identity/aws/latest)
