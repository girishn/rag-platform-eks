output "redis_endpoint" {
  value       = "rediss://${aws_elasticache_serverless_cache.this.endpoint[0].address}:${aws_elasticache_serverless_cache.this.endpoint[0].port}"
  description = "Full rediss:// URL — set as REDIS_URL in LiteLLM Helm values (TLS, no password)"
}

output "security_group_id" {
  value       = aws_security_group.elasticache.id
  description = "ElastiCache security group ID"
}
