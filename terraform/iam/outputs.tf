output "rag_api_role_arn" {
  value       = aws_iam_role.workload["rag-api"].arn
  description = "Pod Identity role ARN for rag-api"
}

output "litellm_role_arn" {
  value       = aws_iam_role.workload["litellm"].arn
  description = "Pod Identity role ARN for litellm"
}

output "ingestion_role_arn" {
  value       = aws_iam_role.workload["ingestion"].arn
  description = "Pod Identity role ARN for ingestion"
}

output "vllm_role_arn" {
  value       = aws_iam_role.workload["vllm"].arn
  description = "Pod Identity role ARN for vllm"
}

output "models_bucket_name" {
  value       = aws_s3_bucket.models.id
  description = "S3 bucket for vLLM model weights"
}

output "models_bucket_arn" {
  value       = aws_s3_bucket.models.arn
  description = "ARN of the S3 models bucket"
}
