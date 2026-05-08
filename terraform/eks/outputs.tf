output "cluster_name" {
  value       = module.eks.cluster_name
  description = "EKS cluster name — consumed by iam/ and addons/ modules"
}

output "cluster_endpoint" {
  value       = module.eks.cluster_endpoint
  description = "EKS API server endpoint"
}

output "cluster_certificate_authority_data" {
  value       = module.eks.cluster_certificate_authority_data
  description = "Base64-encoded cluster CA — used to configure kubectl"
}

output "oidc_provider_arn" {
  value       = module.eks.oidc_provider_arn
  description = "OIDC provider ARN — used by IRSA roles in addons/"
}

output "vpc_id" {
  value       = module.vpc.vpc_id
  description = "VPC ID — consumed by rds/ and elasticache/ modules"
}

output "private_subnet_ids" {
  value       = module.vpc.private_subnets
  description = "Private subnet IDs — used by RDS subnet group and ElastiCache"
}

output "karpenter_node_iam_role_arn" {
  value       = module.karpenter.node_iam_role_arn
  description = "IAM role ARN for Karpenter-provisioned nodes"
}
