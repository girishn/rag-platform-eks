output "endpoint" {
  value       = aws_db_instance.this.endpoint
  description = "RDS endpoint (host:port) — used by rag-api and ingestion connection strings"
}

output "db_name" {
  value       = aws_db_instance.this.db_name
  description = "Initial database name (rag)"
}

output "master_secret_arn" {
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
  description = "Secrets Manager ARN for master credentials — iam/ module grants GetSecretValue to litellm role"
}

output "security_group_id" {
  value       = aws_security_group.rds.id
  description = "RDS security group ID — consumed by elasticache/ for cross-referencing"
}
